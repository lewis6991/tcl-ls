'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const { resolveConfiguredCommand } = require('./command-line');
const {
  LanguageClient,
  RevealOutputChannelOn,
  TransportKind,
} = require('vscode-languageclient/node');

const CONFIG_SECTION = 'tcl-ls';
const SERVER_CONFIG_SECTION = `${CONFIG_SECTION}.server`;
const RESTART_COMMAND = 'tcl-ls.restartServer';
const WATCHED_PROJECT_FILES = [
  { label: 'project config', pattern: '**/tcllsrc.tcl' },
  { label: 'package index', pattern: '**/pkgIndex.tcl' },
  { label: 'metadata', pattern: '**/*.meta.tcl' },
];

let client;
let extensionPath;
let outputChannel;
let restartChain = Promise.resolve();

async function activate(context) {
  extensionPath = context.extensionPath;
  outputChannel = vscode.window.createOutputChannel('tcl-ls');
  context.subscriptions.push(outputChannel);
  context.subscriptions.push({
    dispose() {
      void stopClient();
    },
  });

  context.subscriptions.push(
    vscode.commands.registerCommand(RESTART_COMMAND, async () => {
      await restartClient('manual restart');
      void vscode.window.showInformationMessage('tcl-ls restarted.');
    }),
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (!event.affectsConfiguration(SERVER_CONFIG_SECTION)) {
        return;
      }
      void restartClient('server settings changed');
    }),
  );

  for (const watchedFile of WATCHED_PROJECT_FILES) {
    const watcher = vscode.workspace.createFileSystemWatcher(watchedFile.pattern);
    const handleEvent = (uri) => {
      const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
      if (!config.get('server.restartOnProjectFileChanges', true)) {
        return;
      }
      const relativePath = vscode.workspace.asRelativePath(uri, false);
      void restartClient(`${watchedFile.label} changed: ${relativePath}`);
    };
    watcher.onDidChange(handleEvent, null, context.subscriptions);
    watcher.onDidCreate(handleEvent, null, context.subscriptions);
    watcher.onDidDelete(handleEvent, null, context.subscriptions);
    context.subscriptions.push(watcher);
  }

  try {
    await startClient();
  } catch (error) {
    showStartupError(error);
    throw error;
  }
}

async function deactivate() {
  await stopClient();
}

async function startClient() {
  if (client) {
    return;
  }

  const { description, serverOptions } = createServerOptions();
  outputChannel.appendLine(`Starting tcl-ls with ${description}.`);

  const nextClient = new LanguageClient(
    'tcl-ls',
    'tcl-ls',
    serverOptions,
    {
      documentSelector: [
        { language: 'tcl', scheme: 'file' },
        { language: 'tcl', scheme: 'untitled' },
      ],
      outputChannel,
      revealOutputChannelOn: RevealOutputChannelOn.Never,
      markdown: {
        isTrusted: false,
        supportHtml: false,
      },
    },
  );

  client = nextClient;
  try {
    await nextClient.start();
  } catch (error) {
    client = undefined;
    throw error;
  }
}

async function stopClient() {
  const activeClient = client;
  client = undefined;

  if (activeClient) {
    await activeClient.stop();
  }
}

function restartClient(reason) {
  restartChain = restartChain
    .catch(() => undefined)
    .then(async () => {
      outputChannel.appendLine(`Restarting tcl-ls: ${reason}.`);
      await stopClient();
      await startClient();
    })
    .catch((error) => {
      showStartupError(error);
      throw error;
    });

  return restartChain;
}

function createServerOptions() {
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
  const configuredCommand = config.get('server.command', '').trim();
  const configuredArgs = config.get('server.args', []);
  const configuredRepoRoot = resolveConfiguredPath(config.get('server.repoRoot', null));
  const configuredCwd = resolveConfiguredPath(config.get('server.cwd', null));

  if (configuredCommand) {
    const resolvedConfiguredCommand = resolveConfiguredCommand(configuredCommand, configuredArgs);
    return {
      description: `configured command \`${resolvedConfiguredCommand.description}\``,
      serverOptions: createExecutable(
        resolvedConfiguredCommand.command,
        resolvedConfiguredCommand.args,
        configuredCwd,
      ),
    };
  }

  if (configuredRepoRoot) {
    const serverPath = venvServer(configuredRepoRoot);
    if (!fs.existsSync(serverPath)) {
      throw new Error(
        `No language-server entry point found at ${serverPath}. Run \`uv sync\` in ${configuredRepoRoot} or configure tcl-ls.server.command.`,
      );
    }
    return {
      description: `repoRoot server \`${serverPath}\``,
      serverOptions: createExecutable(serverPath, [], configuredCwd ?? configuredRepoRoot),
    };
  }

  const packagedServer = bundledServer();
  if (packagedServer && fs.existsSync(packagedServer)) {
    return {
      description: `bundled server \`${packagedServer}\``,
      serverOptions: createExecutable(packagedServer, [], configuredCwd),
    };
  }

  return {
    description: '`tcl-ls` on PATH',
    serverOptions: createExecutable('tcl-ls', [], configuredCwd),
  };
}

function createExecutable(command, args, cwd) {
  const executable = {
    command,
    args,
    transport: TransportKind.stdio,
  };
  if (cwd) {
    executable.options = { cwd };
  }
  return {
    run: executable,
    debug: executable,
  };
}

function resolveConfiguredPath(configuredPath) {
  if (!configuredPath) {
    return undefined;
  }

  const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  let resolved = configuredPath;
  if (workspaceFolder) {
    resolved = resolved.replaceAll('${workspaceFolder}', workspaceFolder);
    resolved = resolved.replaceAll(
      '${workspaceFolderBasename}',
      path.basename(workspaceFolder),
    );
    if (!path.isAbsolute(resolved)) {
      resolved = path.resolve(workspaceFolder, resolved);
    }
  }
  return resolved;
}

function venvServer(repoRoot) {
  return process.platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'tcl-ls.exe')
    : path.join(repoRoot, '.venv', 'bin', 'tcl-ls');
}

function bundledServer() {
  if (!extensionPath) {
    return undefined;
  }

  return process.platform === 'win32'
    ? path.join(extensionPath, 'server', 'tcl-ls.exe')
    : path.join(extensionPath, 'server', 'tcl-ls');
}

function showStartupError(error) {
  const message = error instanceof Error ? error.message : String(error);
  const detail =
    'Use the bundled server from the packaged extension, or configure tcl-ls.server.command / args or tcl-ls.server.repoRoot for local development.';
  void vscode.window.showErrorMessage(`tcl-ls failed to start: ${message}. ${detail}`);
}

module.exports = {
  activate,
  deactivate,
};

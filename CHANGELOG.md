# Changelog

## [0.2.0](https://github.com/lewis6991/tcl-ls/compare/v0.1.0...v0.2.0) (2026-03-25)


### Features

* add builtin command metadata ([b1c0e4f](https://github.com/lewis6991/tcl-ls/commit/b1c0e4f4923c09ade10834f84c3fbd1b1bff481b))
* add packaged releases and editor clients ([5b30540](https://github.com/lewis6991/tcl-ls/commit/5b3054051e670d433224950ee26966ddb32694d8))
* **analysis:** add ambiguous variable diagnostic ([f05b94d](https://github.com/lewis6991/tcl-ls/commit/f05b94d5bcf43c259efb2ca8fd05c85ffd2adf4a))
* **analysis:** add arity diagnostics ([8fdde56](https://github.com/lewis6991/tcl-ls/commit/8fdde568609b99ee260016ab74b552b06368086a))
* **analysis:** add option diagnostics ([40af39c](https://github.com/lewis6991/tcl-ls/commit/40af39c9c0795bbf274a5e6f16c8183fa8071cf2))
* **analysis:** add Tcl metadata plugins ([cbceb7c](https://github.com/lewis6991/tcl-ls/commit/cbceb7c93318b099de9500e85f212e815d44e4c5))
* **analysis:** add Tcllib builtin metadata ([746e6a5](https://github.com/lewis6991/tcl-ls/commit/746e6a508d5d0ebc8310422140db8e1e3e3ab887))
* **analysis:** apply package metadata bindings ([1db88cd](https://github.com/lewis6991/tcl-ls/commit/1db88cdc36afb06b20dd14d51696b5b5c1c92448))
* **analysis:** detect unreachable code ([017af66](https://github.com/lewis6991/tcl-ls/commit/017af66f5ec108b4f485b2dbd06bee63de5cce20))
* **analysis:** load Tk and tcltest metadata ([09a47b1](https://github.com/lewis6991/tcl-ls/commit/09a47b16e0094f5e479b6bff612b64d33db8350f))
* **analysis:** model builtin variable flows ([0552208](https://github.com/lewis6991/tcl-ls/commit/0552208650e7e84d415c26733a4051c027afb37d))
* **analysis:** resolve if condition refs ([d7ee00f](https://github.com/lewis6991/tcl-ls/commit/d7ee00fa2e6f3d487efe9d9e9dfb29cb49ea003b))
* **analysis:** support catch builtin ([85b9d58](https://github.com/lewis6991/tcl-ls/commit/85b9d580b64c80949de77fde31b63b796750c68d))
* **analysis:** track variable value flow ([37bdb07](https://github.com/lewis6991/tcl-ls/commit/37bdb07e810515fd1526712fa1997e1097e146b1))
* **analysis:** validate if and switch forms ([d2e30ae](https://github.com/lewis6991/tcl-ls/commit/d2e30aed1426d6c176773af63a5052e4f22de7d6))
* **check:** validate regex patterns ([ff95cad](https://github.com/lewis6991/tcl-ls/commit/ff95cad791473d67b7678b393eebd3dbe9fe2209))
* **cli:** add tcl-check diagnostics runner ([6cde5c9](https://github.com/lewis6991/tcl-ls/commit/6cde5c9b878996d3a501b62127e6cf4f45a677d6))
* **diagnostics:** check builtin subcommands ([c18a011](https://github.com/lewis6991/tcl-ls/commit/c18a011742b32177b427dfe68e64a2e049e13823))
* expand builtin subcommand support ([4e4fb17](https://github.com/lewis6991/tcl-ls/commit/4e4fb17bb2a7e8b032d5eb5f3462e03d273b9c5c))
* **hover:** enrich proc hovers ([466fe0b](https://github.com/lewis6991/tcl-ls/commit/466fe0b42ed72433423c235bd96115916727b8d4))
* **hover:** trace imported command origins ([dfce720](https://github.com/lewis6991/tcl-ls/commit/dfce720aedb2d6ec0ea3b93e12a5872e7a70d998))
* infer packages from pkgIndex ([e66b49c](https://github.com/lewis6991/tcl-ls/commit/e66b49c6331231c7e44cd15862cb0c4847d5d078))
* load static source dependencies ([d129baf](https://github.com/lewis6991/tcl-ls/commit/d129bafcb2c20e9f1ed2bdf211e93753a83ae0c0))
* **lsp:** add editor assistance features ([46865a1](https://github.com/lewis6991/tcl-ls/commit/46865a1de156b10abc52450849bf8aaf8f72b117))
* **lsp:** add more editor methods ([7a2f219](https://github.com/lewis6991/tcl-ls/commit/7a2f21935212e11e6edeb437212c354354152a17))
* **lsp:** add rename support ([e198943](https://github.com/lewis6991/tcl-ls/commit/e1989432025bb5bffbd153945b2ffe56f3138255))
* **lsp:** add semantic token deltas ([8ddfc56](https://github.com/lewis6991/tcl-ls/commit/8ddfc56b52e9392fa7b277e6336409bdceea0873))
* **lsp:** add semantic tokens ([84d2861](https://github.com/lewis6991/tcl-ls/commit/84d28619763b7b64fd7c274e9eea7bbc304cc500))
* **lsp:** define namespace imports ([e4c064c](https://github.com/lewis6991/tcl-ls/commit/e4c064c62f76e49fe0b812b30599972a3677a8c9))
* **lsp:** define package require names ([589427a](https://github.com/lewis6991/tcl-ls/commit/589427ae4bb2fef2ceec252139275f58c9106a51))
* **lsp:** expand completion coverage ([67158d0](https://github.com/lewis6991/tcl-ls/commit/67158d0630600314348a0a4eeab6da3f886f82d2))
* **lsp:** highlight return keyword ([82df2b6](https://github.com/lewis6991/tcl-ls/commit/82df2b610198ba607557b70ec88312a1175da53d))
* **lsp:** highlight semicolon separators ([03ea575](https://github.com/lewis6991/tcl-ls/commit/03ea575ab82276e61069b7c521cb2992c12f6a2a))
* **lsp:** log startup and indexing ([1cac708](https://github.com/lewis6991/tcl-ls/commit/1cac708f57d19783db3b79b2fa62b85d950e8463))
* **lsp:** report indexing progress ([6d3a0fd](https://github.com/lewis6991/tcl-ls/commit/6d3a0fd6705110170759374147943d7e7dfe6051))
* **meta:** analyze dict for bodies ([ce717cd](https://github.com/lewis6991/tcl-ls/commit/ce717cd19b8eacb05fa2424af916ffca9af6a93c))
* **metadata:** add clay definition context ([dd1084a](https://github.com/lewis6991/tcl-ls/commit/dd1084a35dcdd29e112097550b081491240eb7b8))
* **metadata:** add command value enums ([2e668c1](https://github.com/lewis6991/tcl-ls/commit/2e668c148437fd918e14b2cafc9f772d859b8ddb))
* **metadata:** redesign metadata DSL ([5acea60](https://github.com/lewis6991/tcl-ls/commit/5acea6014084777b79232507e4f75b9bee1cf082))
* **metadata:** support project plugin bundles ([6b369ca](https://github.com/lewis6991/tcl-ls/commit/6b369ca8d8b2a9256d50713cfdea1e96e2870925))
* **meta:** describe exec options ([0ac82cd](https://github.com/lewis6991/tcl-ls/commit/0ac82cdf9e9d7260050093bff3844e4be1b99369))
* **parser:** add tcllib corpus coverage ([1759dec](https://github.com/lewis6991/tcl-ls/commit/1759decfa46e838a16266d757a4a62bceff940c8))
* **parser:** support argument expansion ([d4a65f6](https://github.com/lewis6991/tcl-ls/commit/d4a65f664afb487103cdf1cacdc982924ff4d3c1))
* **project:** support external Tcl libs ([e28dca2](https://github.com/lewis6991/tcl-ls/commit/e28dca2344ec20db72f7c69649d3c372a5bee4eb))
* **tcl-meta:** derive proc signatures ([8694cdf](https://github.com/lewis6991/tcl-ls/commit/8694cdfae689ff9f6f7c0223cc0af2c4a10b58a9))


### Bug Fixes

* add more tcllib command metadata ([45a75c4](https://github.com/lewis6991/tcl-ls/commit/45a75c4e31e8d1b04f5ddddae613cac43a6f2fd0))
* **analysis:** analyze switch branch bodies ([ef9dd45](https://github.com/lewis6991/tcl-ls/commit/ef9dd4535bd7e0d5f9ec7bbe3c445f7fe923160f))
* **analysis:** drop return option diagnostics ([1fea62e](https://github.com/lewis6991/tcl-ls/commit/1fea62eb0efd363b5e54e393a145b28dca251d81))
* **analysis:** handle expanded command args ([ff6f804](https://github.com/lewis6991/tcl-ls/commit/ff6f80478b3924dd30ac62d982965cda3566d23a))
* **analysis:** infer switch value domains ([2863a39](https://github.com/lewis6991/tcl-ls/commit/2863a395422a3091e2db864e98be5d1f54d5d342))
* **analysis:** prefer proc implementations ([2889fcd](https://github.com/lewis6991/tcl-ls/commit/2889fcd3de8a100c76bfa88bfe08ff9654ebd00c))
* **analysis:** preserve braced script offsets ([b8cb935](https://github.com/lewis6991/tcl-ls/commit/b8cb935d22ace37ef1fe0164d21e2dd551d23386))
* **analysis:** preserve switch branch positions ([67cbf01](https://github.com/lewis6991/tcl-ls/commit/67cbf01a08c08e3dce602cd262797da786cc997e))
* **analysis:** resolve dynamic array bindings ([923f7f9](https://github.com/lewis6991/tcl-ls/commit/923f7f9598817743608e00f9a49603a17a4b713e))
* **analysis:** support try handlers ([420e024](https://github.com/lewis6991/tcl-ls/commit/420e024c5885871a1c4528ed08e1e194a8177abb))
* **analysis:** track Tcl imports and aliases ([5d7684e](https://github.com/lewis6991/tcl-ls/commit/5d7684e0e009657d1eb28087f4009be9ac76b345))
* **builtins:** override bundled metadata ([a6f0762](https://github.com/lewis6991/tcl-ls/commit/a6f076277cdb76a771f46230ffd84342f05862cd))
* **check:** use helper effect metadata ([8e45ac8](https://github.com/lewis6991/tcl-ls/commit/8e45ac8943a50da027aa9906ce172180cc4f9503))
* **ci:** preserve release artifacts on publish ([4124a7f](https://github.com/lewis6991/tcl-ls/commit/4124a7f3730203a5070dcde1c576da941fa262b4))
* **ci:** roll prerelease into nightly ([c31a76f](https://github.com/lewis6991/tcl-ls/commit/c31a76fc0b656e715ac08ad877e69265ccc0613d))
* **hover:** omit Tcl builtin import notes ([7238456](https://github.com/lewis6991/tcl-ls/commit/723845645401040145fe5593fab2b33c08af0866))
* **lsp:** coalesce stale document changes ([006957e](https://github.com/lewis6991/tcl-ls/commit/006957ecca65bb6374cb140e99fd19451c8442a7))
* **lsp:** complete absolute command prefixes ([2708c1f](https://github.com/lewis6991/tcl-ls/commit/2708c1ffac25a37d6b529bf982168036f1d408e0))
* **lsp:** scope analysis to document deps ([521d8ca](https://github.com/lewis6991/tcl-ls/commit/521d8ca40b31c79e08c6318eaceb72a229a0f111))
* **lsp:** show startup notifications ([2d70a89](https://github.com/lewis6991/tcl-ls/commit/2d70a896b30bfe246090b028d07cc64cc9eabfed))
* **lsp:** sync semantic tokens after edits ([af33789](https://github.com/lewis6991/tcl-ls/commit/af33789fde346edf4777eb59d51dbfa95f84c716))
* **meta:** tighten set arity ([3b6817e](https://github.com/lewis6991/tcl-ls/commit/3b6817e31ef9be978e609e3d0620c359072434ca))
* reduce more tcllib command noise ([2a0e4a6](https://github.com/lewis6991/tcl-ls/commit/2a0e4a663f7b9b61ae1de70a376ca7d39e2c54ce))
* reduce tcllib diagnostic noise ([e66c918](https://github.com/lewis6991/tcl-ls/commit/e66c918abcc3e2b0e42db116b3ae5c032ce9bb44))
* restore frozen server startup ([fe5cae0](https://github.com/lewis6991/tcl-ls/commit/fe5cae044c718e738d137cc626049821e164fff6))


### Performance Improvements

* **check:** parallelize workspace checks ([8b4df98](https://github.com/lewis6991/tcl-ls/commit/8b4df987e9e3c6ea0aa7e87e5e5f47f51fdfa66b))
* **check:** skip lexical span collection ([2e00132](https://github.com/lewis6991/tcl-ls/commit/2e0013250e5eae605fd285071c93043ce7c9e400))
* **lsp:** speed up completion requests ([2364d32](https://github.com/lewis6991/tcl-ls/commit/2364d32e56c938ab55398b7e0f6ce48c891c844c))
* **parser:** batch plain-text scans ([121890f](https://github.com/lewis6991/tcl-ls/commit/121890f783304b85d09f32210ce73fc14b6795e5))
* **parser:** scan braced words in chunks ([f7ff12e](https://github.com/lewis6991/tcl-ls/commit/f7ff12ea17231b3aa72933cc978a858ca772aae2))
* **parser:** track cursor ints locally ([7473a00](https://github.com/lewis6991/tcl-ls/commit/7473a00ce3b03907d3bb47fedc9d2cd045565a07))
* reduce parser and lowering overhead ([8401de9](https://github.com/lewis6991/tcl-ls/commit/8401de9f473661a11f1b4a1f90f9d1060869aca5))
* trim embedded analysis parse overhead ([e5fb459](https://github.com/lewis6991/tcl-ls/commit/e5fb459bcde6caa50ebaf9c9ceef0f137c22434b))


### Documentation

* add commit message skill ([e928a74](https://github.com/lewis6991/tcl-ls/commit/e928a74412e282564e9f2336bfc4138f419c7358))
* add Sphinx docs site ([7c7c48b](https://github.com/lewis6991/tcl-ls/commit/7c7c48b98eee0e0cb026048fd842d2135b13863f))
* link hosted docs in README ([20c7e6e](https://github.com/lewis6991/tcl-ls/commit/20c7e6e580fc6563971d87781eff0e8c4be58412))
* **skill:** keep commit scopes clean ([677074e](https://github.com/lewis6991/tcl-ls/commit/677074e42051dc6c2e3edd93149143a8175dc31c))

## Changelog

All notable changes to this project will be documented in this file.

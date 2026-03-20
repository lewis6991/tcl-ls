from __future__ import annotations

project = 'tcl-ls'
author = 'tcl-ls contributors'
copyright = '2026, tcl-ls contributors'
release = '0.1.0'

extensions: list[str] = []

templates_path: list[str] = []
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'furo'
html_title = 'tcl-ls documentation'
html_static_path = ['_static']
html_css_files = ['custom.css']

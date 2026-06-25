import os
import sys

project = "Aurora"
copyright = "2026, Daniel Huang. Mentor: Zarah Brown."
author = "Daniel Huang"
release = "0.1"

extensions = [
    "sphinx.ext.mathjax",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "project_context"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_baseurl = "https://devxinhuang.github.io/aurora/"
html_theme_options = {
    "logo_only": False,
    "prev_next_buttons_location": "bottom",
    "style_external_links": False,
    "collapse_navigation": True,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "includehidden": True,
    "titles_only": False,
}

html_css_files = ["custom.css"]

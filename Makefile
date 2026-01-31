# FutagAssist Makefile

PYTHON ?= python
VENV ?= .venv/bin/python
SCRIPT_DIR = scripts
CONFIG_DIR = config

.PHONY: help install test lint download-projects list-projects

help:
	@echo "Targets:"
	@echo "  install            - pip install -e ."
	@echo "  test               - pytest tests/"
	@echo "  lint               - ruff check src/"
	@echo "  download-projects  - clone C/C++/Python projects into libs/ (config: config/libs_projects.yaml)"
	@echo "  list-projects      - list projects from config/libs_projects.yaml"

install:
	$(PYTHON) -m pip install -e .

test:
	$(VENV) -m pytest tests/ -v

lint:
	ruff check src/

download-projects:
	$(VENV) $(SCRIPT_DIR)/download_projects.py --output libs

download-projects-shallow:
	$(VENV) $(SCRIPT_DIR)/download_projects.py --output libs --shallow

list-projects:
	$(VENV) $(SCRIPT_DIR)/download_projects.py --list

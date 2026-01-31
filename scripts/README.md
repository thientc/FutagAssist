# Scripts

## download_projects.py

Download top critical C, C++, and Python projects (OSS-Fuzz style) for fuzzing and CodeQL analysis.

**Config:** `config/libs_projects.yaml` — list of projects with `name`, `repo_url`, `language`, optional `branch`, optional `build_type`.

**Usage:**

```bash
# List projects from config
python scripts/download_projects.py --list

# Download all projects into libs/
python scripts/download_projects.py

# Download into a custom directory
python scripts/download_projects.py --output /path/to/repos

# Download a single project
python scripts/download_projects.py --project openssl

# Shallow clone (faster, less disk)
python scripts/download_projects.py --shallow

# Verbose
python scripts/download_projects.py -v
```

**Requirements:** `git`, `pyyaml` (or install project deps: `pip install -e .`).

**Output:** Repos are cloned into `libs/<name>` (or `--output` path). The `libs/` directory is gitignored.

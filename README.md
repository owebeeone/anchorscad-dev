# AnchorSCAD Dev Tree

This repo is only meant to hold git submodules that make up AnchorSCAD and some tools
to make set up the appropriate environment for running the code in this repo.

The reason for this is that AnchorSCAD often pushes changes to PythonOpenScad, Datatrees,
Xdatatrees, and other repos that are no longer part of the AnchorSCAD repo. This repo 
unifies the code in these repos and has set up PYTHONPATH to find the locally checked
out versions of these modules. Hence this combined repo is an easy way to run the
development code in these repos simultaneously.

## Clone Recursively

To recursively clone the `-dev` tree, you can use the following command:

```bash
git clone --recursive https://github.com/owebeeone/anchorscad-dev.git
```

This command will clone the `anchorscad-dev` repository along with all its submodules.

## Use a Virtual Environment

It is recommended to use a virtual environment to run the code in this repo.

```bash
uv venv .dev-venv
```

```bash
source .dev-venv/Scriupts/activate
```

or

```bat
.dev-venv\Scripts\activate.bat
```

## Install Dependencies

To run the code in this repo, you will need to have the following dependencies installed:

```bash
uv pip install -r requirements.txt
```

-or- (uv is faster)

```bash
pip install -r requirements.txt
```

## Configure VSCode

This repo has a `.vscode/settings.json`, `.vscode/launch.json`, and `.vscode/.env` that
should be used to configure VSCode to use the correct PYTHONPATH and environment
variables. If this is not working for you, there is a `dev-setup` script that can be
used to rewrite the `.vscode/*` files to use the correct PYTHONPATH.

```bash
python dev-setup/src/vscode_configutator/vscode_configutator.py
```

## Update Requirements

If you add new dependencies to the repo, you will need to update the `requirements.txt`
file and `pyproject.toml` file. Once that is done you can use the `collect_dependencies.py`
script to collect the dependencies and update the `requirements.txt` file.

```bash
python dev-setup/src/collect_dependencies/collect_dependencies.py
```




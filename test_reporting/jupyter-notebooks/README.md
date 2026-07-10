# Jupyter Notebooks

## Overview
This directory hosts a collection (currently only one) of jupyter notebooks for performing analysis on SONiC devices.

## Usage

Create and activate python virtual env for installing depencies:
```
python3.11 -m venv jupyter-venv
. jupyter-venv/bin/activate
```

Install the dependencies
```
pip install -r requirements.txt
```

Kusto access defaults to interactive login for local notebook use. To use Azure CLI authentication instead, set `KUSTO_AUTH_MODE=az_cli` after running `az login`; this is also the mode used by the SONiC Shift ETL pipeline in CI.

Open the notebook in vscode and run it.

## Tips

When upstreaming code, make sure the notebook ouptut is cleared.

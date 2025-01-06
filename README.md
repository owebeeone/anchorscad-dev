# AnchorSCAD Dev Tree

This repo is only meant to hold git submodules that make up AnchorSCAD.

To recursively clone the `-dev` tree, you can use the following command:

```bash
git clone --recursive https://github.com/owebeeone/anchorscad-dev.git
```

This command will clone the `anchorscad-dev` repository along with all its submodules.

Running VSCode from this folder should use a PYTHONPATH that finds the locally checked
out versions of these modules.



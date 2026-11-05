"""What Python's msilib offers on this PC (read-only): tables in its schema,
standard actions in its sequences, and the class signatures used to build
an MSI.

    python tools/probe_msilib.py
"""
import inspect
import warnings

warnings.simplefilter("ignore")


def main():
    import msilib
    from msilib import schema, sequence
    print("msilib", msilib.__file__, "Win64:", getattr(msilib, "Win64", None))
    print("schema tables:", sorted(t.name for t in schema.tables))
    for name in ("InstallExecuteSequence", "InstallUISequence",
                 "AdminExecuteSequence"):
        rows = getattr(sequence, name)
        print(name, [r[0] for r in rows if r[0] in (
            "FindRelatedProducts", "RemoveExistingProducts", "InstallValidate",
            "InstallInitialize", "InstallFinalize", "CreateFolders",
            "LockPermissions", "MsiLockPermissionsEx", "AppSearch",
            "LaunchConditions", "WriteRegistryValues", "CreateShortcuts",
            "MigrateFeatureStates")], [(r[0], r[2]) for r in rows if r[0] in (
            "FindRelatedProducts", "RemoveExistingProducts",
            "InstallValidate", "InstallInitialize")])
    for obj in (msilib.init_database, msilib.Directory.__init__,
                msilib.Directory.start_component, msilib.Directory.add_file,
                msilib.Feature.__init__, msilib.CAB.__init__,
                msilib.add_data):
        print(obj.__qualname__, inspect.signature(obj))
    print(inspect.getsource(msilib.init_database))
    print(inspect.getsource(msilib.Directory.start_component))
    print(inspect.getsource(msilib.CAB.commit))


if __name__ == "__main__":
    main()

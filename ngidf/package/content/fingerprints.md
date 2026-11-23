<!-- Appendix C of the QC package. Same definition as the Prefect plan artifact and ngidf/qa/report.py. -->

Each stage of the pipeline has a **fingerprint**: a SHA-256 hash of everything the stage uses to make its
outputs.

- The exact contents of its scripts.
- The contents of its input files, or the fingerprints of the earlier stages whose outputs it reads.
- Its settings, such as the list of places or the model commit.
- The fingerprint of the software environment it runs in.

Any change, even one character of a script or a new model version, gives a new fingerprint. A stage's
outputs are kept in a folder named after its fingerprint. A stage therefore runs again only when
something it uses has changed, and earlier results are never overwritten. Because a stage's fingerprint
includes those of the stages it reads from, a change re-runs exactly the stages downstream of it, and no
others.

Some things are left out of the fingerprint because they cannot change the results: where the code was
checked out, who ran it and when, and the checks themselves, which can be run again on existing outputs.

One shortcut is deliberate. The 86 TB WRF/CESM archive is identified by its path rather than by hashing
its contents. It is SNAP's read-only archive, and its file counts and sizes are listed below.

"Adopted" marks outputs made before the pipeline existed. They were registered with the pipeline instead
of being recomputed, and checked again like any other output.

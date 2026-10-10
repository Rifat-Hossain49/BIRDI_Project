# CPU Pilot Approval and Submission

Date: 2026-10-04, Asia/Dhaka.

The user explicitly approved the prior request to upload recovered transcripts
and RTL artifacts as a private Kaggle dataset under `tishaferdous` and run the
CPU-only interruption/resume pilot ("yes go ahead"). The publishing action was
then accepted and the first notebook version was submitted successfully.

Notebook: https://www.kaggle.com/code/tishaferdous/confibench-cpu-only-interruption-replay-validation

Dataset: `tishaferdous/cbq-replay-cpu-oct4-data`, private (no public-create flag).

Submitted metadata has `enable_gpu: false`, `is_private: true`. The notebook
contains no model download or model-server startup. Fresh-call budget is zero.
The initial live status was `RUNNING`. This does not yet prove recovery succeeds.

Kaggle chose a slug derived from the title rather than the originally requested
identifier. The local metadata and observer use the actual returned identifier.

The ConfiBench GPU launch hold remains in place. This submission is only a
validation experiment, not an additional scored benchmark result.

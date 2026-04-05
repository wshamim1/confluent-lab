# Security Examples

This folder contains local, self-managed Kafka security examples intended for learning and adaptation.

## Included Example

- `local-sasl-ssl/` - a single-broker local example using `SASL_SSL` with sample broker and client properties

## Important Notes

- these files are learning templates, not production-ready drop-ins
- the example favors clarity over full automation
- for production, prefer stronger credential and certificate lifecycle management
- if you use SASL/PLAIN for local learning, move to SCRAM, mTLS, or your approved platform standard for real deployments
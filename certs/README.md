Optional. If your machine runs an antivirus or proxy that inspects HTTPS (e.g. Kaspersky),
export its root CA as PEM and save it here as `extra-ca.pem`. The n8n container trusts it via
`NODE_EXTRA_CA_CERTS`. Files in this folder are git-ignored.

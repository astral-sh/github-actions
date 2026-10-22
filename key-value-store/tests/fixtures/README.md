The certificate and private key in this directory are public test fixtures for
the local HTTPS server. They do not authenticate any deployed service. The
entrypoint tests trust this certificate only in their child processes through
`NODE_EXTRA_CA_CERTS`.

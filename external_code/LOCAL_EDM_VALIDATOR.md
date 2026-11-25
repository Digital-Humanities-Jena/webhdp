# Local EDM Validator Source Checkout

WebHDP integrates with `Digital-Humanities-Jena/local-edm-validator` as a pinned
external source checkout. The upstream source is not vendored in this repository.

Use the managed setup script from the repository root:

```sh
make local-edm-validator-setup
```

This clones `https://github.com/Digital-Humanities-Jena/local-edm-validator`,
checks out the pinned commit recorded in `.env.example` and initializes the
validator's Metis Schema `v15` submodule. The validator builds its bundled XSDs
and RDF bindings from that source.

Verify the checkout before building the EDM validator overlay:

```sh
make local-edm-validator-verify
```

Then start the managed validator stack:

```sh
docker compose -f docker-compose.yml -f docker-compose.edm-validator.yml up --build
```

The upstream project retains its own license and release process.

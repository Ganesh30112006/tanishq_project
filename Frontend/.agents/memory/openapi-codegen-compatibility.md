---
name: OpenAPI codegen compatibility
description: Non-obvious constraints for Orval-generated API clients and Zod schemas in this workspace.
---

Use numeric OpenAPI fields instead of integer formats when the generated Zod package does not expose `z.int()`. Path/query operations can also produce the same parameter name in both generated API schemas and generated TypeScript types; the public Zod barrel must re-export those types explicitly and omit the duplicate symbol.

**Why:** The workspace currently pairs Orval output with a Zod version whose runtime API and generated barrel names are not fully aligned with the OpenAPI generator defaults.

**How to apply:** After every OpenAPI change, run codegen and the library typecheck. If codegen appends a broad generated-types export, preserve the explicit barrel exports so duplicate generated parameter names do not break the build.
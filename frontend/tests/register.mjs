// Lets Node run the TypeScript sources as they are written: `import "./router.js"` means ./router.ts (the way the bundler reads it). No dependencies.
import { register } from "node:module";
register("./resolve-ts.mjs", import.meta.url);

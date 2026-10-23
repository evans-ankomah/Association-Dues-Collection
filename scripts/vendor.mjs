// Copies browser libraries from node_modules into static/vendor so Django serves them locally.
import { copyFileSync, mkdirSync } from "node:fs";

const files = [
  ["node_modules/htmx.org/dist/htmx.min.js", "static/vendor/htmx.min.js"],
  ["node_modules/alpinejs/dist/cdn.min.js", "static/vendor/alpine.min.js"],
];

mkdirSync("static/vendor", { recursive: true });
for (const [from, to] of files) {
  copyFileSync(from, to);
  console.log(`vendored ${to}`);
}

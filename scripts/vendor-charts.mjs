import { copyFile, mkdir } from "node:fs/promises";

const source = "node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js";
const targetDir = "src/finorch/dashboard/static/vendor";
const target = `${targetDir}/lightweight-charts.js`;

await mkdir(targetDir, { recursive: true });
await copyFile(source, target);
console.log(`Copied ${source} -> ${target}`);

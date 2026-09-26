// Run with the Khronos glTF Validator available through NODE_PATH.
const fs = require('node:fs');
const path = require('node:path');
const validator = require('gltf-validator');

function files(directory) {
  return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? files(file) : (file.endsWith('.glb') ? [file] : []);
  });
}

(async () => {
  const directory = process.argv[2];
  if (!directory) throw new Error('Usage: node conformance.cjs RESULT_DIR');
  const results = [];
  for (const file of files(directory)) {
    const result = await validator.validateBytes(new Uint8Array(fs.readFileSync(file)), {maxIssues: 100});
    results.push({file: path.relative(directory, file), ...result.issues});
  }
  fs.writeFileSync(path.join(directory, 'conformance.json'), JSON.stringify(results, null, 2));
  console.log(`${results.length} models; ${results.reduce((sum, item) => sum + item.numErrors, 0)} errors; ${results.reduce((sum, item) => sum + item.numWarnings, 0)} warnings`);
  if (!results.length || results.some(item => item.numErrors || item.numWarnings)) process.exitCode = 1;
})().catch(error => { console.error(error.message); process.exitCode = 1; });

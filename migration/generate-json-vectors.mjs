// Node is the independent oracle for the compact JSON format used by format 1.
import { writeFile } from 'node:fs/promises';
const inputJson = [
  '-0', '1e-6', '1e-7', '1e20', '1e21', '9007199254740993',
  '1000000000000000128', '1.7976931348623157e308', '5e-324',
  '{"10":"ten","2":"two","01":"leading","4294967295":"ordinary","4294967294":"index","name":"last"}',
  '{"line":"\\n\\t\\u0000\\u2028\\u2029","pair":"\\ud83d\\ude00","lone":"\\ud83d"}',
  '{"tool":{"arguments":{"count":9007199254740993,"ratio":1e-7}}}',
];
await writeFile(process.argv[2], JSON.stringify({
  issue: 'SYL-95', check: 'migration.ecmascript-json', node: process.version,
  vectors: inputJson.map(input => ({ inputJson: input, expected: JSON.stringify(JSON.parse(input)) })),
}, null, 2) + '\n');

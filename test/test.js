const { execSync } = require('child_process');

function run(cmd) {
  console.log('  $', cmd);
  const out = execSync(cmd, { encoding: 'utf-8' });
  console.log(out.split('\n').slice(0, 6).map(l => '    ' + l).join('\n'));
  return out;
}

console.log('quilt-canon-cli self-test');
console.log('');

// help
console.log('--- canon (help) ---');
run('node bin/canon help');

console.log('--- canon count ---');
run('node bin/canon count');

console.log('--- canon claim "trust ladder" ---');
run('node bin/canon claim "trust ladder"');

console.log('--- canon hash ---');
run('node bin/canon hash');

console.log('--- canon paper 470 ---');
run('node bin/canon paper 470');

console.log('  ✓ all checks passed (if no errors thrown)');

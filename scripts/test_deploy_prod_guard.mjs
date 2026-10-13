// Offline check using GitHub's expression evaluator, installed outside the repo:
// npm install --prefix /tmp/fmaj-prod-expression-check --no-audit --no-fund @actions/expressions@0.3.0 tsx@4.20.6
// /tmp/fmaj-prod-expression-check/node_modules/.bin/tsx scripts/test_deploy_prod_guard.mjs /tmp/fmaj-prod-expression-check
// tsx resolves the evaluator package's extensionless ESM imports.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const { Parser, Lexer, Evaluator, data } = await import(pathToFileURL(resolve(
  process.argv[2], 'node_modules/@actions/expressions/dist/index.js',
)));
const workflow = readFileSync(new URL('../.github/workflows/deploy-prod.yml', import.meta.url), 'utf8');
const guard = workflow.match(/^    if: \$\{\{ (.+) \}\}$/m)?.[1];
assert.ok(guard, 'Missing production job guard');
const expression = new Parser(new Lexer(guard).lex().tokens, ['github'], []).parse();

let cases = 0;
for (const event of ['workflow_dispatch', 'push', 'pull_request']) {
  for (const ref of ['refs/heads/main', 'refs/heads/develop', 'refs/heads/feature', 'refs/tags/main', '']) {
    const context = new data.Dictionary({
      key: 'github',
      value: new data.Dictionary(
        { key: 'event_name', value: new data.StringData(event) },
        { key: 'ref', value: new data.StringData(ref) },
      ),
    });
    assert.equal(
      new Evaluator(expression, context).evaluate().coerceString(),
      String(event === 'workflow_dispatch' && ref === 'refs/heads/main'),
      `${event} at ${ref}`,
    );
    cases++;
  }
}
console.log(`${cases} production job guard cases passed; no credentials or dispatches requested.`);

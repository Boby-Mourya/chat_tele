// Syntax-only check. It does not replace tsc --noEmit, the Vite build, or React tests.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
const local = path.join(root, 'frontend/node_modules/typescript');
const compiler = fs.existsSync(local) ? local : path.join(cp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'typescript');
const ts = require(compiler);
const files = [
  'App.tsx', 'components/OrganizationProfileWizard.tsx', 'components/WorkspaceBrandEffects.tsx',
  'components/WorkspaceSetup.tsx', 'components/brand.tsx', 'components/providers.tsx',
  'lib/brand-assets.ts', 'lib/setup-api.ts', 'lib/workspace-api.ts', 'pages/WhiteLabelPage.tsx',
];
const errors = [];
for (const relative of files) {
  const file = path.join(root, 'frontend/src', relative);
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
    reportDiagnostics: true,
  });
  for (const diagnostic of result.diagnostics ?? []) {
    if (diagnostic.category === ts.DiagnosticCategory.Error) errors.push({ file: relative, message: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n') });
  }
}
console.log(JSON.stringify({ scope: 'Syntax only; not semantic typechecking or a production build', files: files.length, errors }, null, 2));
if (errors.length) process.exit(1);

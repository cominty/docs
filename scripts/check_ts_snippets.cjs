#!/usr/bin/env node
/**
 * Syntax-check every ```ts / ```typescript / ```js / ```javascript code fence
 * in the docs.
 *
 * Snippets are illustrative fragments (often assuming a `client` and top-level
 * `await` in an ES module), not standalone scripts, so we parse rather than run
 * or type-check them. This is the JavaScript twin of check_snippets.py.
 *
 *     npm install --no-save --no-package-lock typescript@5.9.3
 *     node scripts/check_ts_snippets.cjs
 *
 * The pre-commit hook installs `typescript` in its own environment instead.
 */

const fs = require('node:fs')
const path = require('node:path')

function loadTypeScript() {
    try {
        return require('typescript')
    } catch {}
    // pre-commit's `language: node` installs additional_dependencies globally
    // into its environment, which `require` does not search on its own.
    const prefix = process.env.npm_config_prefix || process.env.NPM_CONFIG_PREFIX
    if (prefix) {
        for (const dir of [path.join(prefix, 'lib', 'node_modules'), path.join(prefix, 'node_modules')]) {
            try {
                return require(path.join(dir, 'typescript'))
            } catch {}
        }
    }
    console.error('typescript is not installed. Run: npm install --no-save --no-package-lock typescript@5.9.3')
    process.exit(2)
}

const ts = loadTypeScript()

const ROOT = path.resolve(__dirname, '..')
const SKIP_DIRS = new Set(['.git', 'node_modules', '.mint', '.mintlify', 'draft'])
const FENCE_RE = /^([ \t]*)```(ts|typescript|js|javascript)(?![\w-])[^\n]*\n([\s\S]*?)^\1```/gm

function* docFiles(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
            if (!SKIP_DIRS.has(entry.name)) yield* docFiles(path.join(dir, entry.name))
        } else if (/\.mdx?$/.test(entry.name)) {
            yield path.join(dir, entry.name)
        }
    }
}

function dedent(text, indent) {
    return text
        .split('\n')
        .map((line) => (line.startsWith(indent) ? line.slice(indent.length) : line.trimStart()))
        .join('\n')
}

function checkFile(file) {
    const errors = []
    const text = fs.readFileSync(file, 'utf8')
    let index = 0
    for (const match of text.matchAll(FENCE_RE)) {
        index += 1
        const [, indent, lang, body] = match
        const code = dedent(body, indent)
        const name = `${path.relative(ROOT, file)}#snippet-${index}`
        const kind = lang.startsWith('j') ? ts.ScriptKind.JS : ts.ScriptKind.TS
        // An ES module, so top-level `await` and `import` are allowed.
        const source = ts.createSourceFile(`${name}.mts`, code, ts.ScriptTarget.ESNext, true, kind)
        for (const diagnostic of source.parseDiagnostics) {
            const { line, character } = source.getLineAndCharacterOfPosition(diagnostic.start ?? 0)
            const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')
            errors.push(`${name}:${line + 1}:${character + 1}: ${message}`)
        }
    }
    return { errors, count: index }
}

let files = 0
let snippets = 0
const allErrors = []
for (const file of docFiles(ROOT)) {
    files += 1
    const { errors, count } = checkFile(file)
    snippets += count
    allErrors.push(...errors)
}

console.log(`checked ${snippets} ts/js snippet(s) in ${files} doc file(s)`)
if (allErrors.length) {
    console.log(`found ${allErrors.length} syntax error(s):`)
    for (const error of allErrors) console.log(`  ${error}`)
    process.exit(1)
}
console.log('all ts/js snippets parse cleanly')

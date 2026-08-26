module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint", "react-hooks"],
  ignorePatterns: ["dist", "node_modules", ".eslintrc.cjs"],
  rules: {
    // XSS: React escapes text but not raw HTML, and not hrefs.
    "react/no-danger": "off",
    "no-restricted-properties": [
      "error",
      {
        object: "document",
        property: "write",
        message: "document.write is an XSS vector; render through React.",
      },
    ],
    "no-restricted-syntax": [
      "error",
      {
        selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
        message:
          "dangerouslySetInnerHTML injects unescaped markup. Every string in this app comes from an API that carries customer- and merchant-authored text; render it as text.",
      },
      {
        selector: "CallExpression[callee.name='eval']",
        message: "eval is blocked by the CSP and has no business here.",
      },
    ],
    "@typescript-eslint/no-explicit-any": "error",
  },
};

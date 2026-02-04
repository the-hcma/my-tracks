import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import globals from "globals";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
      },
      parserOptions: {
        projectService: {
          allowDefaultProject: ["web_ui/static/web_ui/ts/*.test.ts"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // TypeScript strict rules
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/explicit-function-return-type": [
        "error",
        { allowExpressions: true, allowConciseArrowFunctionExpressionsStartingWithVoid: true },
      ],
      "@typescript-eslint/no-explicit-any": "error",

      // Code quality
      "no-console": "off", // Allow console for debugging
      "prefer-const": "error",
      "no-var": "error",
    },
  },
  {
    ignores: ["web_ui/static/web_ui/js/**", "node_modules/**"],
  }
);

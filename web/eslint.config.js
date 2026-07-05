import tsParser from '@typescript-eslint/parser';
import globals from 'globals';

export default [
  {
    ignores: ['node_modules/**', 'static/**', '**/*.test.ts'],
  },
  {
    linterOptions: {
      reportUnusedDisableDirectives: 'warn',
    },
  },
  {
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parser: tsParser,
      globals: {
        ...globals.browser,
        ...globals.es2024,
      },
    },
    rules: {
      // Type safety
      'eqeqeq': ['error', 'always', { null: 'ignore' }],
      'no-constant-binary-expression': 'error',
      'no-fallthrough': 'error',
      'prefer-const': 'warn',

      // Code quality
      'no-duplicate-imports': 'warn',
      'no-unused-vars': ['warn', {
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_|^e$',
        varsIgnorePattern: '^_',
      }],

      // Production safety ? allow console.warn/error, warn on log/debug
      'no-console': ['warn', { allow: ['warn', 'error', 'debug'] }],
      'no-debugger': 'error',

      // Modern JS
      'no-var': 'error',
      'prefer-arrow-callback': 'warn',
    },
  },
  {
    // Test files have relaxed rules
    files: ['src/**/*.test.ts'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parser: tsParser,
      globals: { ...globals.browser, ...globals.es2024 },
    },
    rules: {
      'no-console': 'off',
      'no-unused-vars': 'off',
    },
  },
];

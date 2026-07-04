import tsParser from '@typescript-eslint/parser';
import globals from 'globals';

export default [
  {
    ignores: ['node_modules/**', 'static/**'],
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
      'eqeqeq': ['warn', 'always', { null: 'ignore' }],
      'no-constant-binary-expression': 'warn',
      'no-duplicate-imports': 'warn',
      'no-fallthrough': 'warn',
      'no-unused-vars': ['warn', {
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      }],
      'prefer-const': 'warn',
    },
  },
];

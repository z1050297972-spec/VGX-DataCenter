// 前端检查配置（工单 02）；使用已批准插件，不依赖 jiti、globals 或 @eslint/js。
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsdoc from "eslint-plugin-jsdoc";
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";

// 覆盖命名函数、箭头和函数表达式；有文档的私有函数也检查契约内容。
const functionContexts = ["FunctionDeclaration", "ArrowFunctionExpression", "FunctionExpression"];
const functionContext =
  ":matches(FunctionDeclaration, ArrowFunctionExpression, FunctionExpression)";

export default tseslint.config(
  {
    // 生成类型不手改（规范 8.2），由 B 的过期检查验证；依赖和构建产物不作源码检查。
    ignores: ["node_modules/**", "dist/**", "src/api/schema.d.ts"],
  },
  { linterOptions: { reportUnusedDisableDirectives: "error" } },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [tseslint.configs.strictTypeChecked, reactHooks.configs.flat.recommended],
    languageOptions: {
      parserOptions: { project: "./tsconfig.json", tsconfigRootDir: import.meta.dirname },
      // no-restricted-globals 检查对象属性时需已登记的全局；只登记浏览器入口，不新增 globals 依赖。
      globals: { window: "readonly", self: "readonly" },
    },
    plugins: { jsdoc, "eslint-comments": eslintComments },
    settings: {
      jsdoc: {
        mode: "typescript",
        // 自定义标签只含文字，不把第一词误判为参数名或类型。
        structuredTags: {
          sideEffects: { name: false, type: false },
          timeSemantics: { name: false, type: false },
        },
      },
    },
    rules: {
      // 后端分支数 ≤ 12 无 ESLint 对等规则，用圈复杂度 ≤ 10 兜底。
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='style']",
          message: "静态样式使用 CSS 类；运行时值须说明原因，见 CODING_STANDARDS 10.9。",
        },
      ],
      complexity: ["error", 10],
      "max-params": ["error", 5],
      "max-statements": ["error", 40],
      "no-console": "error",
      "no-restricted-globals": [
        "error",
        {
          globals: [{ name: "fetch", message: "请求必须通过 api/client 的客户端工厂。" }],
          // 同样拦截 window.fetch 和 globalThis.fetch，避免绕过统一请求边界。
          checkGlobalObject: true,
        },
      ],
      "eslint-comments/no-unlimited-disable": "error",
      "eslint-comments/require-description": "error",
      "@typescript-eslint/ban-ts-comment": [
        "error",
        {
          "ts-ignore": true,
          "ts-expect-error": "allow-with-description",
          "ts-nocheck": true,
          "ts-check": false,
          minimumDescriptionLength: 3,
        },
      ],
      "jsdoc/require-jsdoc": [
        "error",
        {
          publicOnly: true,
          enableFixer: false,
          exemptEmptyFunctions: false,
          require: {
            FunctionDeclaration: true,
            ArrowFunctionExpression: true,
            FunctionExpression: true,
          },
        },
      ],
      "jsdoc/check-tag-names": ["error", { definedTags: ["sideEffects", "timeSemantics"] }],
      "jsdoc/require-description": ["error", { contexts: functionContexts }],
      "jsdoc/require-param": "error",
      "jsdoc/check-param-names": "error",
      "jsdoc/require-param-description": "error",
      // require-tags 按每个函数检查，避免 no-missing-syntax 只保证文件里至少有一份。
      // G2：只有真实参数才写 @param，由 require-param 与 check-param-names 核对签名。
      "jsdoc/require-tags": [
        "error",
        {
          tags: [
            { tag: "returns", context: functionContext },
            { tag: "throws", context: functionContext },
            { tag: "sideEffects", context: functionContext },
            { tag: "timeSemantics", context: functionContext },
          ],
        },
      ],
      // 只要求非空，不强加英文大写或句点；@throws 无 与中文标点都合法。
      "jsdoc/match-description": [
        "error",
        {
          contexts: functionContexts,
          matchDescription: "\\S",
          tags: {
            param: true,
            returns: true,
            throws: true,
            sideEffects: true,
            timeSemantics: true,
          },
        },
      ],
    },
  },
  {
    // 等 M2 合并后清理，见 ui-style followups。
    files: ["src/accounts/Pages.tsx", "src/jobs/Pages.tsx"],
    rules: { "no-restricted-syntax": "off" },
  },
);

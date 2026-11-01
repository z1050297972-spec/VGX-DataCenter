// 样式边界遵循 CODING_STANDARDS 10.7、10.10、10.11 和 10.13。
export default {
  extends: "stylelint-config-standard",
  reportDescriptionlessDisables: true,
  reportNeedlessDisables: true,
  rules: {
    // Prettier 管理空行；不强制既有注释、规则和 at-rule 前加空行。
    "comment-empty-line-before": null,
    "rule-empty-line-before": null,
    "at-rule-empty-line-before": null,
    // 保留既有 min/max-width 断点写法，避免纯形式改写。
    "media-feature-range-notation": null,
    // 保留字体名的常见拼写，大小写不影响 CSS 关键字匹配。
    "value-keyword-case": null,
    // 旧版 WebKit 仍需要前缀以支持 backdrop-filter。
    "property-no-vendor-prefix": null,
    // 既有 :not 写法合法，改成复杂形式不提升可读性。
    "selector-not-notation": null,
    // 既有规则的层叠顺序有意保留，避免重排导致视觉变化。
    "no-descending-specificity": null,
    "color-no-hex": true,
    "color-named": "never",
    "function-disallowed-list": ["rgb", "rgba", "hsl", "hsla"],
    "selector-class-pattern": "^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    "selector-max-compound-selectors": 3,
    "selector-max-id": 0,
    "declaration-no-important": true,
    "media-feature-name-allowed-list": ["width", "min-width", "max-width"],
  },
  overrides: [
    {
      files: ["src/shell.css"],
      rules: {
        // 设计变量和全局降级只在 shell.css 定义。
        "color-no-hex": null,
        "color-named": null,
        "function-disallowed-list": null,
        "media-feature-name-allowed-list": null,
      },
    },
  ],
};

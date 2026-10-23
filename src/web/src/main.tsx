// 浏览器入口只调用挂载函数；测试导入 mountWeb 模块时不会自动挂载。
import { mountWeb } from "./mountWeb";

mountWeb(document.getElementById("root"));

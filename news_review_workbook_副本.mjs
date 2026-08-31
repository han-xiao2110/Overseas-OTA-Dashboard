import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [mode, inputPath, outputPath] = process.argv.slice(2);
if (!mode || !inputPath || !outputPath) {
  throw new Error("usage: news_review_workbook_副本.mjs <export|import|verify> <input> <output>");
}

const headers = [
  "序号", "日期", "标题", "摘要", "来源", "当前模块", "当前判断", "新规则建议",
  "当前分数", "新规则分数", "样本标签", "命中规则", "筛选理由", "URL", "打开原文",
  "用户标注", "排除原因", "备注",
];

function excelString(value) {
  return String(value ?? "").replaceAll('"', '""');
}

async function exportWorkbook() {
  const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
  const rows = payload.rows || [];
  const workbook = Workbook.create();
  const instructions = workbook.worksheets.add("说明");
  const review = workbook.worksheets.add("待标注新闻");
  instructions.showGridLines = false;
  review.showGridLines = false;

  instructions.mergeCells("A1:H2");
  instructions.getRange("A1").values = [["OTA 新闻筛选初始标注清单"]];
  instructions.getRange("A1:H2").format = {
    fill: "#7F1D1D", font: { bold: true, color: "#FFFFFF", size: 18 },
    verticalAlignment: "center", horizontalAlignment: "left",
  };
  const info = [
    ["生成时间", payload.generated_at || ""],
    ["规则版本", payload.policy_version || ""],
    ["本批条数", Number(payload.review_size || rows.length)],
    ["操作说明", "只需填写“用户标注”；排除时建议补充“排除原因”，必要时填写备注。"],
    ["标注含义", "保留＝应该进入看板；排除＝不应进入；不确定＝暂不改变规则。"],
    ["规则边界", "Hotel 默认排除，仅直接影响 OTA 的分销、佣金、直订竞争、平台合作、AI 预订入口和监管例外保留。"],
    ["注意", "本清单不会每日生成；后续仅在需要校准时按需补充。"],
  ];
  instructions.getRange(`A4:B${3 + info.length}`).values = info;
  instructions.getRange("A4:A10").format = { font: { bold: true, color: "#7F1D1D" }, fill: "#FCE7E7" };
  instructions.getRange("B4:B10").format = { wrapText: true, verticalAlignment: "top" };
  instructions.getRange("A4:B10").format.borders = { preset: "outside", style: "thin", color: "#D9D9D9" };
  instructions.getRange("A:A").format.columnWidth = 16;
  instructions.getRange("B:B").format.columnWidth = 88;
  instructions.getRange("4:10").format.rowHeight = 34;

  review.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
  const values = rows.map((r, idx) => [
    idx + 1, r.date || "", r.title || "", r.summary || "", r.source || "",
    r.current_module || "", r.current_decision || "", r.proposed_decision || "",
    Number(r.current_score || 0), Number(r.proposed_score || 0), r.review_tags || "",
    r.matched_rules || "", r.selection_reasons || "", r.url || "", "",
    "", "", "",
  ]);
  if (values.length) {
    review.getRangeByIndexes(1, 0, values.length, headers.length).values = values;
    for (let i = 0; i < values.length; i += 1) {
      const url = excelString(rows[i].url || "");
      review.getCell(i + 1, 14).formulas = [[url ? `=HYPERLINK("${url}","打开原文")` : ""]];
    }
  }
  const lastRow = Math.max(2, rows.length + 1);
  review.getRange(`A1:R${lastRow}`).format = { verticalAlignment: "top" };
  review.getRange("A1:R1").format = {
    fill: "#7F1D1D", font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center", verticalAlignment: "center", wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#6B1616" },
  };
  review.getRange(`A2:R${lastRow}`).format.borders = {
    insideHorizontal: { style: "thin", color: "#E5E7EB" },
    bottom: { style: "thin", color: "#D1D5DB" },
  };
  review.getRange(`C2:D${lastRow}`).format.wrapText = true;
  review.getRange(`K2:M${lastRow}`).format.wrapText = true;
  review.getRange(`P2:R${lastRow}`).format.wrapText = true;
  review.getRange(`P2:P${lastRow}`).format.fill = "#FFF7D6";
  review.getRange(`Q2:R${lastRow}`).format.fill = "#FFFDF3";
  review.getRange(`I2:J${lastRow}`).format.numberFormat = "0";
  review.getRange(`P2:P${lastRow}`).dataValidation = {
    allowBlank: true,
    list: { inCellDropDown: true, source: ["保留", "排除", "不确定"] },
  };
  review.getRange(`Q2:Q${lastRow}`).dataValidation = {
    allowBlank: true,
    list: {
      inCellDropDown: true,
      source: ["Hotel非OTA相关", "软广", "评论观点", "低价值", "分类错误", "其他"],
    },
  };
  review.getRange(`P2:P${lastRow}`).conditionalFormats.add("containsText", {
    text: "保留", format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
  });
  review.getRange(`P2:P${lastRow}`).conditionalFormats.add("containsText", {
    text: "排除", format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
  });
  review.getRange(`P2:P${lastRow}`).conditionalFormats.add("containsText", {
    text: "不确定", format: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } },
  });
  review.freezePanes.freezeRows(1);
  review.freezePanes.freezeColumns(2);
  review.tables.add(`A1:R${lastRow}`, true, "NewsReviewTable").style = "TableStyleMedium2";
  const widths = [7, 12, 42, 52, 18, 20, 12, 14, 11, 12, 24, 32, 46, 48, 12, 12, 18, 28];
  widths.forEach((width, idx) => {
    review.getRangeByIndexes(0, idx, lastRow, 1).format.columnWidth = width;
  });
  review.getRange("1:1").format.rowHeight = 32;
  if (rows.length) review.getRange(`2:${lastRow}`).format.rowHeight = 60;

  const out = await SpreadsheetFile.exportXlsx(workbook);
  await out.save(outputPath);
  process.stdout.write(JSON.stringify({ rows: rows.length, output: outputPath }));
}

async function importWorkbook() {
  const blob = await FileBlob.load(inputPath);
  const workbook = await SpreadsheetFile.importXlsx(blob);
  const sheet = workbook.worksheets.getItem("待标注新闻");
  const used = sheet.getUsedRange(true);
  const matrix = used ? used.values : [];
  if (!matrix || matrix.length < 1) throw new Error("待标注新闻工作表为空");
  const header = matrix[0].map((x) => String(x ?? "").trim());
  const required = ["标题", "来源", "URL", "用户标注", "排除原因", "备注"];
  for (const name of required) {
    if (!header.includes(name)) throw new Error(`缺少必要列: ${name}`);
  }
  const rows = [];
  for (const raw of matrix.slice(1)) {
    const row = {};
    header.forEach((name, idx) => { row[name] = raw[idx] ?? ""; });
    if (String(row["标题"] || "").trim() || String(row["URL"] || "").trim()) rows.push(row);
  }
  await fs.writeFile(outputPath, JSON.stringify(rows, null, 2), "utf8");
  process.stdout.write(JSON.stringify({ rows: rows.length, output: outputPath }));
}

async function verifyWorkbook() {
  const blob = await FileBlob.load(inputPath);
  const workbook = await SpreadsheetFile.importXlsx(blob);
  const sheets = await workbook.inspect({ kind: "sheet", include: "id,name" });
  const review = await workbook.inspect({
    kind: "table", sheetId: "待标注新闻", range: "A1:R31",
    include: "values,formulas", tableMaxRows: 31, tableMaxCols: 18, maxChars: 16000,
  });
  const errors = await workbook.inspect({
    kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan",
  });
  const prefix = outputPath.replace(/\.json$/i, "");
  const infoPng = `${prefix}_说明.png`;
  const reviewPng = `${prefix}_待标注新闻.png`;
  const infoImage = await workbook.render({ sheetName: "说明", range: "A1:H10", scale: 1.5, format: "png" });
  const reviewImage = await workbook.render({ sheetName: "待标注新闻", range: "A1:R8", scale: 1, format: "png" });
  await fs.writeFile(infoPng, new Uint8Array(await infoImage.arrayBuffer()));
  await fs.writeFile(reviewPng, new Uint8Array(await reviewImage.arrayBuffer()));
  const result = {
    sheets: sheets.ndjson, review: review.ndjson, errors: errors.ndjson,
    previews: [infoPng, reviewPng],
  };
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf8");
  process.stdout.write(JSON.stringify({ output: outputPath, previews: result.previews }));
}

if (mode === "export") await exportWorkbook();
else if (mode === "import") await importWorkbook();
else if (mode === "verify") await verifyWorkbook();
else throw new Error(`unsupported mode: ${mode}`);

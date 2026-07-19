import { index, integer, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const institutions = sqliteTable("institutions", {
  id: integer("id").primaryKey({ autoIncrement: true }), sourceName: text("source_name").notNull(),
  canonicalName: text("canonical_name").notNull(), campus: text("campus"),
}, (table) => [uniqueIndex("institution_name_idx").on(table.sourceName, table.canonicalName)]);

export const documents = sqliteTable("documents", {
  id: integer("id").primaryKey({ autoIncrement: true }), institutionId: integer("institution_id").notNull().references(() => institutions.id),
  admissionYear: integer("admission_year").notNull(), admissionCycle: text("admission_cycle").notNull().default("수시"),
  localPath: text("local_path").notNull().unique(), sourceUrl: text("source_url"), sha256: text("sha256"), pageCount: integer("page_count"),
});

export const admissionTracks = sqliteTable("admission_tracks", {
  id: integer("id").primaryKey({ autoIncrement: true }), documentId: integer("document_id").notNull().references(() => documents.id),
  name: text("name").notNull(), normalizedCategory: text("normalized_category").notNull().default("특성화고교졸업자"),
  isVocational: integer("is_vocational", { mode: "boolean" }).notNull().default(true), isEmployedWorker: integer("is_employed_worker", { mode: "boolean" }).notNull().default(false),
});

export const programs = sqliteTable("programs", {
  id: integer("id").primaryKey({ autoIncrement: true }), institutionId: integer("institution_id").notNull().references(() => institutions.id),
  name: text("name").notNull(), normalizedName: text("normalized_name").notNull(), fieldGroup: text("field_group").notNull(),
}, (table) => [index("program_field_idx").on(table.fieldGroup, table.normalizedName)]);

export const results = sqliteTable("results", {
  id: integer("id").primaryKey({ autoIncrement: true }), trackId: integer("track_id").notNull().references(() => admissionTracks.id),
  programId: integer("program_id").notNull().references(() => programs.id), pageNumber: integer("page_number").notNull(), tableIndex: integer("table_index").notNull(),
  rowIndex: integer("row_index").notNull(), quota: integer("quota"), applicants: integer("applicants"), competitionRate: real("competition_rate"),
  registrants: integer("registrants"), waitlistRank: integer("waitlist_rank"), representativeGrade: real("representative_grade"),
  representativeGradeBasis: text("representative_grade_basis"), extractionConfidence: real("extraction_confidence").notNull(), rawRowJson: text("raw_row_json").notNull(),
}, (table) => [index("result_grade_idx").on(table.representativeGrade)]);

export const metrics = sqliteTable("metrics", {
  id: integer("id").primaryKey({ autoIncrement: true }), resultId: integer("result_id").notNull().references(() => results.id, { onDelete: "cascade" }),
  metricCode: text("metric_code").notNull(), sourceLabel: text("source_label").notNull(), valueNumeric: real("value_numeric"), valueText: text("value_text"),
  unit: text("unit"), cohort: text("cohort"), percentile: real("percentile"), stage: text("stage"),
}, (table) => [index("metric_code_value_idx").on(table.metricCode, table.valueNumeric)]);

export const rawTables = sqliteTable("raw_tables", {
  id: integer("id").primaryKey({ autoIncrement: true }), documentId: integer("document_id").notNull().references(() => documents.id),
  pageNumber: integer("page_number").notNull(), tableIndex: integer("table_index").notNull(), extractionStrategy: text("extraction_strategy").notNull(), rowsJson: text("rows_json").notNull(),
});

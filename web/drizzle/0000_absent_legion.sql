CREATE TABLE `admission_tracks` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`document_id` integer NOT NULL,
	`name` text NOT NULL,
	`normalized_category` text DEFAULT '특성화고교졸업자' NOT NULL,
	`is_vocational` integer DEFAULT true NOT NULL,
	`is_employed_worker` integer DEFAULT false NOT NULL,
	FOREIGN KEY (`document_id`) REFERENCES `documents`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `documents` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`institution_id` integer NOT NULL,
	`admission_year` integer NOT NULL,
	`admission_cycle` text DEFAULT '수시' NOT NULL,
	`local_path` text NOT NULL,
	`source_url` text,
	`sha256` text,
	`page_count` integer,
	FOREIGN KEY (`institution_id`) REFERENCES `institutions`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `documents_local_path_unique` ON `documents` (`local_path`);--> statement-breakpoint
CREATE TABLE `institutions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`source_name` text NOT NULL,
	`canonical_name` text NOT NULL,
	`campus` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `institution_name_idx` ON `institutions` (`source_name`,`canonical_name`);--> statement-breakpoint
CREATE TABLE `metrics` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`result_id` integer NOT NULL,
	`metric_code` text NOT NULL,
	`source_label` text NOT NULL,
	`value_numeric` real,
	`value_text` text,
	`unit` text,
	`cohort` text,
	`percentile` real,
	`stage` text,
	FOREIGN KEY (`result_id`) REFERENCES `results`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `metric_code_value_idx` ON `metrics` (`metric_code`,`value_numeric`);--> statement-breakpoint
CREATE TABLE `programs` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`institution_id` integer NOT NULL,
	`name` text NOT NULL,
	`normalized_name` text NOT NULL,
	`field_group` text NOT NULL,
	FOREIGN KEY (`institution_id`) REFERENCES `institutions`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `program_field_idx` ON `programs` (`field_group`,`normalized_name`);--> statement-breakpoint
CREATE TABLE `raw_tables` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`document_id` integer NOT NULL,
	`page_number` integer NOT NULL,
	`table_index` integer NOT NULL,
	`extraction_strategy` text NOT NULL,
	`rows_json` text NOT NULL,
	FOREIGN KEY (`document_id`) REFERENCES `documents`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `results` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`track_id` integer NOT NULL,
	`program_id` integer NOT NULL,
	`page_number` integer NOT NULL,
	`table_index` integer NOT NULL,
	`row_index` integer NOT NULL,
	`quota` integer,
	`applicants` integer,
	`competition_rate` real,
	`registrants` integer,
	`waitlist_rank` integer,
	`representative_grade` real,
	`representative_grade_basis` text,
	`extraction_confidence` real NOT NULL,
	`raw_row_json` text NOT NULL,
	FOREIGN KEY (`track_id`) REFERENCES `admission_tracks`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`program_id`) REFERENCES `programs`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `result_grade_idx` ON `results` (`representative_grade`);
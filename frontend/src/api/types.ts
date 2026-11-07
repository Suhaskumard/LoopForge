// Shapes mirror backend/app/schemas/*. Keep in sync with docs/api_documentation.md.

export type TaskStatus =
  | "PENDING"
  | "PLANNING"
  | "GENERATING"
  | "EXECUTING"
  | "TESTING"
  | "REVIEWING"
  | "REPAIRING"
  | "COMPLETED"
  | "FAILED"
  | "ESCALATED"
  | "CANCELLED";

export const TERMINAL: TaskStatus[] = ["COMPLETED", "FAILED", "ESCALATED", "CANCELLED"];
export const isTerminal = (s: string): boolean => (TERMINAL as string[]).includes(s);

export interface User {
  id: string;
  email: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  language: string;
}

export interface Task {
  id: string;
  project_id: string;
  requirement: string;
  status: TaskStatus;
  max_iterations: number;
  current_iteration: number;
  acceptance_criteria: string[];
  version: number;
  created_at: string;
}

export interface AgentRun {
  id: string;
  iteration_id: string;
  agent_name: string;
  input_summary: string;
  output_summary: string;
  status: string;
  tokens_used: number;
  duration_seconds: number;
  error_message: string | null;
  started_at: string;
}

export interface Iteration {
  id: string;
  task_id: string;
  number: number;
  status: string;
  quality_score: number | null;
  started_at: string;
  completed_at: string | null;
  tests: { total_tests?: number; passed?: number; failed?: number; skipped?: number; coverage?: number | null };
  decision: { action: string; fingerprint?: string } | null;
  repair: { root_cause?: string; explanation?: string; files_modified?: string[] } | null;
}

export interface TestResult {
  id: string;
  total_tests: number;
  passed: number;
  failed: number;
  skipped: number;
  coverage: number | null;
  details: {
    failures?: { nodeid: string; message: string; traceback: string }[];
    timed_out?: boolean;
  };
}

export interface RuffFinding {
  code: string;
  message: string;
  file: string;
  line: number;
}

export interface Review {
  critical_issues: string[];
  acceptance_criteria: { criterion: string; met: boolean; evidence: string }[];
  requirement_coverage: { req_id: string; covered: boolean }[];
  maintainability_notes: string[];
  quality_score: number;
  unapproved_high_severity?: string[];
}

export interface IterationDetail extends Iteration {
  test_results: TestResult[];
  agent_runs: AgentRun[];
  review: Review | null;
  quality: {
    ruff: RuffFinding[];
    bandit_high: { test_id?: string; issue?: string; file?: string; line?: number }[];
    bandit_other: number;
    tool_errors: string[];
  } | null;
  files: FileEntry[];
}

export interface FileEntry {
  path: string;
  sha256: string;
  iteration: number;
}

export interface FileContent {
  path: string;
  sha256: string;
  content: string;
}

export interface LogEntry {
  name: string;
  sha256: string;
  content: string;
}

export interface FileDiff {
  path: string;
  status: "added" | "removed" | "modified";
  diff: string;
}

export interface IterationDiff {
  iteration: number;
  against: number | null;
  files: FileDiff[];
}

export interface Requirement {
  req_id: string;
  description: string;
  req_type: string;
  priority: string;
  impl_mapping: string[];
  test_mapping: string[];
  verification_status: string;
}

export interface Overview {
  tasks_total: number;
  tasks_by_status: Record<string, number>;
  eligible_finished: number;
  completed: number;
  task_success_rate: number | null;
  average_iterations: number | null;
  test_pass_rate: number | null;
  tests_executed: number;
  tests_passed: number;
  average_quality_score: number | null;
  average_execution_seconds: number | null;
  average_cost: number | null;
  total_tokens: number;
  total_cost: number;
  iteration_efficiency: number | null;
  failure_distribution: Record<string, number>;
  repair_outcomes: Record<string, Record<string, number>>;
  cost_is_estimate: boolean;
  recent_tasks: { id: string; requirement: string; status: TaskStatus; iterations: number; created_at: string }[];
}

export interface IterationStat {
  number: number;
  status: string;
  quality_score: number | null;
  tests_total: number;
  tests_passed: number;
  tests_failed: number;
  coverage: number | null;
  tokens: number;
  duration_seconds: number;
}

export interface TaskAnalytics {
  task_id: string;
  status: string;
  iterations: IterationStat[];
  total_tokens: number;
  estimated_cost: number;
  execution_seconds: number | null;
  quality_trend: (number | null)[];
  failure_categories: Record<string, number>;
}

export interface AgentStat {
  agent: string;
  runs: number;
  successes: number;
  failures: number;
  success_rate: number | null;
  average_duration_seconds: number | null;
  tokens: number;
}

export interface LiveEvent {
  id: string;
  event: string;
  task_id: string;
  timestamp: string;
  agent?: string;
  iteration?: number | null;
  status?: string;
  tests_passed?: number;
  tests_failed?: number;
  tokens?: number;
  duration_seconds?: number;
  files?: string[];
}

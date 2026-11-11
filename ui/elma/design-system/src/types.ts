export type RecordItem = {
  id: string;
  title: string;
  subtitle?: string;
  kind?: string;
  status?: string;
  meta?: string;
  description?: string;
};
export type FieldSpec = {
  key: string;
  label: string;
  type?: 'text' | 'textarea' | 'select' | 'password' | 'url' | 'datetime-local';
  required?: boolean;
  hint?: string;
  options?: string[];
};

export interface WorkspaceRoot {
  root?: string;
  name: string;
  status: string;
  failed?: { reason: string };
}

export interface WorkspaceRootChoice {
  root: string;
  name: string;
  status: 'preparing' | 'working' | 'failed';
  unavailable?: string;
}

export interface WorkspaceRootSelector {
  load: () => Promise<WorkspaceRootChoice[]>;
  open: (root: string) => Promise<void>;
}

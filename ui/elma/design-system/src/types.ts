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

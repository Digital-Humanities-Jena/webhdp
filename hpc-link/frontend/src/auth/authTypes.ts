export type UserProfile = {
  username: string;
  is_admin: boolean;
  invited: boolean;
  is_active: boolean;
  allowed_partitions: string[];
  allowed_gpu_types: string[];
  max_duration_minutes: number;
  max_gpu_count: number;
  last_login?: string | null;
};

export type LoginResponse = {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: UserProfile;
};

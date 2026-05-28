import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../api/client';
import { getApiErrorMessage } from '../api/errors';
import type { UserProfile } from '../auth/authTypes';

type InviteUserRequest = {
  username: string;
  password: string;
  allowed_partitions: string[];
  allowed_gpu_types: string[];
  max_duration_minutes: number;
  max_gpu_count: number;
  is_active: boolean;
};

type PolicyDraft = {
  allowed_partitions: string;
  allowed_gpu_types: string;
  max_duration_minutes: number;
  max_gpu_count: number;
  is_active: boolean;
};

const csvToArray = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

const userToPolicyDraft = (user: UserProfile): PolicyDraft => ({
  allowed_partitions: user.allowed_partitions.join(', '),
  allowed_gpu_types: user.allowed_gpu_types.join(', '),
  max_duration_minutes: user.max_duration_minutes,
  max_gpu_count: user.max_gpu_count,
  is_active: user.is_active,
});

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const [invite, setInvite] = useState<InviteUserRequest>({
    username: '',
    password: '',
    allowed_partitions: ['partition-a'],
    allowed_gpu_types: [],
    max_duration_minutes: 30,
    max_gpu_count: 1,
    is_active: true,
  });

  const [drafts, setDrafts] = useState<Record<string, PolicyDraft>>({});
  const [passwordDrafts, setPasswordDrafts] = useState<Record<string, string>>({});

  const { data: users } = useQuery({
    queryKey: ['admin-users'],
    queryFn: async () => {
      const response = await api.get<UserProfile[]>('/admin/users');
      return response.data;
    },
  });

  const inviteMutation = useMutation({
    mutationFn: async () => {
      const payload: InviteUserRequest = {
        ...invite,
        allowed_partitions: invite.allowed_partitions,
        allowed_gpu_types: invite.allowed_gpu_types,
      };
      await api.post('/admin/users', payload);
    },
    onSuccess: () => {
      toast.success('User invited');
      setInvite({
        username: '',
        password: '',
        allowed_partitions: ['partition-a'],
        allowed_gpu_types: [],
        max_duration_minutes: 30,
        max_gpu_count: 1,
        is_active: true,
      });
      void queryClient.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (error: unknown) => {
      toast.error(getApiErrorMessage(error, 'Failed to invite user'));
    },
  });

  const updatePolicyMutation = useMutation({
    mutationFn: async ({ username, policy }: { username: string; policy: PolicyDraft }) => {
      await api.patch(`/admin/users/${encodeURIComponent(username)}`, {
        allowed_partitions: csvToArray(policy.allowed_partitions),
        allowed_gpu_types: csvToArray(policy.allowed_gpu_types),
        max_duration_minutes: Number(policy.max_duration_minutes),
        max_gpu_count: Number(policy.max_gpu_count),
        is_active: policy.is_active,
      });
    },
    onSuccess: () => {
      toast.success('Policy updated');
      void queryClient.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (error: unknown) => {
      toast.error(getApiErrorMessage(error, 'Failed to update policy'));
    },
  });

  const resetPasswordMutation = useMutation({
    mutationFn: async ({ username, password }: { username: string; password: string }) => {
      await api.post(`/admin/users/${encodeURIComponent(username)}/password`, { password });
    },
    onSuccess: () => {
      toast.success('Password updated');
    },
    onError: (error: unknown) => {
      toast.error(getApiErrorMessage(error, 'Failed to reset password'));
    },
  });

  const nonAdminUsers = useMemo(() => users?.filter((user) => !user.is_admin) ?? [], [users]);

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">User Management</h1>
        <p className="text-muted-foreground">Invite users and set node/time allocation limits.</p>
      </div>

      <section className="rounded-xl border bg-card p-6 shadow-sm space-y-4">
        <h2 className="text-lg font-semibold">Invite User</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium">Username</label>
            <input
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={invite.username}
              onChange={(event) => setInvite((prev) => ({ ...prev, username: event.target.value }))}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Temporary Password</label>
            <input
              type="password"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={invite.password}
              onChange={(event) => setInvite((prev) => ({ ...prev, password: event.target.value }))}
            />
          </div>
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium">Allowed Partitions (comma-separated)</label>
            <input
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={invite.allowed_partitions.join(', ')}
              onChange={(event) =>
                setInvite((prev) => ({ ...prev, allowed_partitions: csvToArray(event.target.value) }))
              }
            />
          </div>
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium">Allowed GPU Types (optional, comma-separated)</label>
            <input
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={invite.allowed_gpu_types.join(', ')}
              onChange={(event) =>
                setInvite((prev) => ({ ...prev, allowed_gpu_types: csvToArray(event.target.value) }))
              }
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Max Duration (minutes)</label>
            <input
              type="number"
              min={1}
              max={10080}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={invite.max_duration_minutes}
              onChange={(event) =>
                setInvite((prev) => ({ ...prev, max_duration_minutes: Number(event.target.value) || 1 }))
              }
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Max GPU Count</label>
            <input
              type="number"
              min={1}
              max={16}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={invite.max_gpu_count}
              onChange={(event) =>
                setInvite((prev) => ({ ...prev, max_gpu_count: Number(event.target.value) || 1 }))
              }
            />
          </div>
        </div>

        <button
          type="button"
          disabled={inviteMutation.isPending}
          onClick={() => inviteMutation.mutate()}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {inviteMutation.isPending ? 'Inviting...' : 'Invite User'}
        </button>
      </section>

      <section className="rounded-xl border bg-card p-6 shadow-sm space-y-4">
        <h2 className="text-lg font-semibold">Existing Users</h2>
        <div className="space-y-4">
          {nonAdminUsers.map((user) => {
            const draft = drafts[user.username] ?? userToPolicyDraft(user);

            return (
              <div key={user.username} className="rounded-lg border bg-background p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{user.username}</p>
                    <p className="text-xs text-muted-foreground">Last login: {user.last_login || 'never'}</p>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.is_active}
                      onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [user.username]: {
                            ...(prev[user.username] ?? userToPolicyDraft(user)),
                            is_active: event.target.checked,
                          },
                        }))
                      }
                    />
                    Active
                  </label>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <input
                    className="rounded-md border bg-card px-3 py-2 text-sm"
                    value={draft.allowed_partitions}
                    onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [user.username]: {
                            ...(prev[user.username] ?? userToPolicyDraft(user)),
                            allowed_partitions: event.target.value,
                          },
                        }))
                    }
                    placeholder="Allowed partitions"
                  />
                  <input
                    className="rounded-md border bg-card px-3 py-2 text-sm"
                    value={draft.allowed_gpu_types}
                    onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [user.username]: {
                            ...(prev[user.username] ?? userToPolicyDraft(user)),
                            allowed_gpu_types: event.target.value,
                          },
                        }))
                    }
                    placeholder="Allowed GPU types"
                  />
                  <input
                    type="number"
                    min={1}
                    max={10080}
                    className="rounded-md border bg-card px-3 py-2 text-sm"
                    value={draft.max_duration_minutes}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [user.username]: {
                          ...prev[user.username],
                          ...(prev[user.username] ?? userToPolicyDraft(user)),
                          max_duration_minutes: Number(event.target.value) || 1,
                        },
                      }))
                    }
                    placeholder="Max minutes"
                  />
                  <input
                    type="number"
                    min={1}
                    max={16}
                    className="rounded-md border bg-card px-3 py-2 text-sm"
                    value={draft.max_gpu_count}
                    onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [user.username]: {
                            ...(prev[user.username] ?? userToPolicyDraft(user)),
                            max_gpu_count: Number(event.target.value) || 1,
                          },
                        }))
                    }
                    placeholder="Max GPU count"
                  />
                </div>

                <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                  <input
                    type="password"
                    minLength={8}
                    className="rounded-md border bg-card px-3 py-2 text-sm"
                    value={passwordDrafts[user.username] || ''}
                    onChange={(event) =>
                      setPasswordDrafts((prev) => ({ ...prev, [user.username]: event.target.value }))
                    }
                    placeholder="Reset password"
                  />
                  <button
                    type="button"
                    className="rounded-lg border px-3 py-2 text-sm"
                    onClick={() => {
                      const password = passwordDrafts[user.username] || '';
                      if (password.length < 8) {
                        toast.error('Password must be at least 8 characters');
                        return;
                      }
                      resetPasswordMutation.mutate({ username: user.username, password });
                    }}
                  >
                    Reset Password
                  </button>
                  <button
                    type="button"
                    className="rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                    onClick={() => updatePolicyMutation.mutate({ username: user.username, policy: draft })}
                  >
                    Save Policy
                  </button>
                </div>
              </div>
            );
          })}

          {nonAdminUsers.length === 0 && (
            <p className="text-sm text-muted-foreground">No invited users yet.</p>
          )}
        </div>
      </section>
    </div>
  );
}

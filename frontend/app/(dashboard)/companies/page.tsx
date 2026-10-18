"use client";

import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/common/page-header";
import { Gate } from "@/components/common/gate";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Table, TableWrap, Td, Th } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Notice, Loading } from "@/components/common/notice";
import { api, errorMessage } from "@/lib/api-client";
import { CAN, can } from "@/lib/roles";
import { formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";
import { useAuthRole } from "@/lib/use-role";

function AddCompany({ onDone }: { onDone: (id: string) => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await api<{ company: { id: string } }>("companies", { method: "POST", body: { name: name.trim() } });
      setName("");
      onDone(result.company.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Add a company" description="A client whose books you keep. Each company's data is separate." />
      <CardBody>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Field label="Company name" htmlFor="company-name" className="min-w-[16rem] flex-1">
            <Input id="company-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ABC Manufacturing" required />
          </Field>
          <Button type="submit" loading={busy} disabled={!name.trim()}>
            Add company
          </Button>
        </form>
        {error ? <Notice kind="error" className="mt-3">{error}</Notice> : null}
      </CardBody>
    </Card>
  );
}

export default function CompaniesPage() {
  const { companies, company, setCompanyId, reloadCompanies, loading } = useWorkspace();
  const role = useAuthRole();

  return (
    <>
      <PageHeader title="Companies" description="The client companies of your firm. The company you pick here is the one every other screen shows." />
      <Gate>
        {() => (
          <div className="space-y-6">
            <Card>
              <CardHeader title="Your companies" />
              {loading ? <Loading /> : null}
              <TableWrap>
                <Table>
                  <thead>
                    <tr>
                      <Th>Name</Th>
                      <Th>Added</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {companies.map((c) => (
                      <tr key={c.id}>
                        <Td className="font-medium">{c.name}</Td>
                        <Td className="text-ink-soft">{formatDateTime(c.created_at)}</Td>
                        <Td align="right">
                          {company?.id === c.id ? (
                            <Badge tone="ledger">Open</Badge>
                          ) : (
                            <Button size="sm" variant="secondary" onClick={() => setCompanyId(c.id)}>
                              Open
                            </Button>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </TableWrap>
            </Card>
            {can(role, CAN.createCompany) ? (
              <AddCompany
                onDone={async (id) => {
                  await reloadCompanies();
                  setCompanyId(id);
                }}
              />
            ) : (
              <Notice kind="info">Adding a company needs a senior accountant, CA or admin.</Notice>
            )}
          </div>
        )}
      </Gate>
    </>
  );
}

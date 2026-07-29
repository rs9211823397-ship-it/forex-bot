import { NextResponse } from "next/server";
import { getAuthUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const user = await getAuthUser(req);
  if (!user) return NextResponse.json({ authenticated: false }, { status: 401 });
  return NextResponse.json({ authenticated: true, user: { id: user.id, username: user.username, role: user.role } });
}

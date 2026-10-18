import { redirect } from "next/navigation";

// The middleware sends signed-out visitors to /login first; anyone who gets here is signed in.
export default function Home() {
  redirect("/dashboard");
}
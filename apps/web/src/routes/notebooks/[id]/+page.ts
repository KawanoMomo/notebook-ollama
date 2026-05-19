export const ssr = false;
export const prerender = false;

export function load({ params }: { params: { id: string } }) {
  return { notebookId: params.id };
}

<script lang="ts">
  import '../app.css';
  import AppHeader from '$lib/components/AppHeader.svelte';
  import Toast from '$lib/components/Toast.svelte';
  let { children } = $props();
</script>

<AppHeader />
<main>
  {@render children()}
</main>
<Toast />

<style>
  main {
    min-height: calc(100vh - var(--header-height));
  }
</style>

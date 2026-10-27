<script lang="ts">
  import Modal from './Modal.svelte';
  import Button from '../components/Button.svelte';
  let {
    title = 'Delete this work item?',
    description = 'The item and its saved settings will be permanently removed.',
    action = 'Delete item',
    actionTone = 'danger',
    onconfirm = () => {},
    oncancel = () => {},
  }: {
    title?: string;
    description?: string;
    action?: string;
    actionTone?: 'primary'|'danger';
    onconfirm?: () => void;
    oncancel?: () => void;
  } = $props();
</script>

<Modal initialFocus="footer button" {title} onclose={oncancel} width={480}
  ><p>{description}</p>
  {#snippet footer()}<Button label="Cancel" onclick={oncancel} /><Button
      label={action}
      tone={actionTone}
      onclick={onconfirm}
    />{/snippet}</Modal
>

const form = document.getElementById('lead-form');
const responseMessage = document.getElementById('response-message');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const formData = Object.fromEntries(new FormData(form));

  responseMessage.textContent = 'Sending your lead...';

  try {
    const response = await fetch('/api/leads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });

    const data = await response.json();
    responseMessage.textContent = data.message || 'Lead submitted successfully.';
  } catch (error) {
    responseMessage.textContent = 'Unable to deliver your lead right now.';
  }
});

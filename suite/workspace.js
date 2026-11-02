const systems = [
  'Cited Knowledge Agent','Document Extraction','Support Operator','Analytics Copilot',
  'Model Router','Memory Service','Claim Auditor','Case Workflow','Multi-Hop Brief'
];
const nav = document.createElement('nav');
nav.className = 'suite-nav';
nav.setAttribute('aria-label', 'Suite navigation');
const home = new URL(location.href);
const current = systems.indexOf(document.querySelector('h1')?.textContent.trim()) + 1;
home.port = String(Number(location.port) - current); home.pathname = '/'; home.search = ''; home.hash = '';
const brand = document.createElement('a');
brand.className = 'suite-brand'; brand.href = home.href;
brand.innerHTML = '<span class="suite-mark" aria-hidden="true">E/</span> Enterprise AI Systems';
nav.append(brand);
const select = document.createElement('select');
select.setAttribute('aria-label', 'Switch application');
select.add(new Option('Explore the suite', '0'));
systems.forEach((title, index) => select.add(new Option(`${String(index+1).padStart(2,'0')} / ${title}`, String(index+1))));
select.value = String(current);
if (select.selectedIndex < 0) select.value = '0';
select.addEventListener('change', () => {
  const target = new URL(home); target.port = String(Number(home.port) + Number(select.value)); location.assign(target.href);
});
document.querySelectorAll('.system-row').forEach((link, index) => {
  const target = new URL(home); target.port = String(Number(home.port) + index + 1); link.href = target.href;
});
nav.append(select);
const docs = document.createElement('a');
docs.href = '/docs'; docs.className = 'suite-docs'; docs.textContent = 'API reference ↗';
nav.append(docs);
document.body.prepend(nav);
const footer = document.createElement('footer');
footer.className = 'suite-footer';
footer.textContent = 'Enterprise AI Systems / Local engineering workspace · Sample data · Model output requires verification';
document.body.append(footer);

const searchInput = document.querySelector('#story-search');
const filters = [...document.querySelectorAll('.genre-filter')];
const stories = [...document.querySelectorAll('.story-card')];
const emptyState = document.querySelector('#empty-state');
let activeGenre = 'all';

function updateStories() {
  const query = searchInput.value.trim().toLowerCase();
  let visibleCount = 0;
  stories.forEach((story) => {
    const text = `${story.dataset.title} ${story.dataset.author} ${story.dataset.genre}`.toLowerCase();
    const visible = text.includes(query) && (activeGenre === 'all' || story.dataset.genre === activeGenre);
    story.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  emptyState.hidden = visibleCount !== 0;
}

filters.forEach((filter) => filter.addEventListener('click', () => {
  activeGenre = filter.dataset.genre;
  filters.forEach((item) => item.classList.toggle('active', item === filter));
  updateStories();
}));
searchInput.addEventListener('input', updateStories);
document.querySelector('#current-year').textContent = new Date().getFullYear();

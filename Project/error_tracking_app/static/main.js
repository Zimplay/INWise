document.addEventListener('DOMContentLoaded', function() {
    let currentErrorId = null;
    const errorList = document.querySelector('.error-list');
    const modal = new bootstrap.Modal(document.getElementById('errorDetailModal'));

    // Load initial errors
    loadErrors('all');

    // Setup navigation listeners
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
            e.target.classList.add('active');
            loadErrors(e.target.dataset.status);
        });
    });

    // Setup filters
    const filters = {
        severity: document.getElementById('severityFilter'),
        component: document.getElementById('componentFilter'),
        search: document.getElementById('searchFilter'),
        source: document.getElementById('sourceFilter')
    };

    Object.values(filters).forEach(filter => {
        if (filter) {
            filter.addEventListener('change', () => applyFilters());
            filter.addEventListener('keyup', () => applyFilters());
        }
    });

    // Добавляем обработчик для кнопки синхронизации
    document.getElementById('syncButton').addEventListener('click', function() {
        const button = this;
        // Отключаем кнопку на время синхронизации
        button.disabled = true;
        const originalText = button.innerHTML;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Syncing...';

        // Отправляем запрос на синхронизацию
        fetch('/api/sync', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                force: true  // Принудительная синхронизация
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'skipped') {
                alert(data.message);
            } else if (data.message && data.message.includes('Sync completed successfully')) {
                alert('Synchronization completed successfully');
                // Перезагружаем список ошибок
                loadErrors('all');
            } else {
                throw new Error(data.message || 'Unknown error occurred');
            }
        })
        .catch(error => {
            console.error('Sync error:', error);
            alert('Sync failed: ' + error.message);
        })
        .finally(() => {
            // Восстанавливаем кнопку
            button.disabled = false;
            button.innerHTML = originalText;
        });
    });

    // Setup resolve button
    document.getElementById('resolveError').addEventListener('click', () => {
        if (currentErrorId) {
            resolveError(currentErrorId);
        }
    });

    function loadErrors(status = 'all') {
        const sourceFilter = filters.source ? filters.source.value : 'all';
        fetch(`/api/errors?status=${status}&source=${sourceFilter}`)
            .then(response => response.json())
            .then(errors => {
                displayErrors(errors);
            })
            .catch(error => console.error('Error loading errors:', error));
    }

    function displayErrors(errors) {
        errorList.innerHTML = errors.map(error => `
            <div class="card error-card error-severity-${error.severity}" data-error-id="${error.id}">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <h5 class="card-title">${error.error_type}</h5>
                        <div>
                            <span class="badge ${error.status === 'resolved' ? 'resolved-badge' : 'open-badge'}">${error.status}</span>
                            <span class="badge bg-info">${error.source}</span>
                            ${error.inwise_id ? `<span class="badge bg-secondary">INWise ID: ${error.inwise_id}</span>` : ''}
                        </div>
                    </div>
                    <h6 class="card-subtitle mb-2 text-muted">${error.affected_component}</h6>
                    <p class="card-text">${error.message}</p>
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="error-timestamp">${new Date(error.timestamp).toLocaleString()}</span>
                        <button class="btn btn-primary btn-sm view-details">View Details</button>
                    </div>
                </div>
            </div>
        `).join('');

        // Add click listeners to view details buttons
        document.querySelectorAll('.view-details').forEach(button => {
            button.addEventListener('click', (e) => {
                const errorId = e.target.closest('.error-card').dataset.errorId;
                showErrorDetails(errors.find(err => err.id === parseInt(errorId)));
            });
        });
    }

    function showErrorDetails(error) {
        currentErrorId = error.id;
        const modalBody = document.querySelector('#errorDetailModal .modal-body');
        
        modalBody.innerHTML = `
            <div class="error-details">
                <div class="d-flex justify-content-between">
                    <h4>${error.error_type}</h4>
                    <div>
                        <span class="badge ${error.status === 'resolved' ? 'resolved-badge' : 'open-badge'}">${error.status}</span>
                        <span class="badge bg-info">${error.source}</span>
                        ${error.inwise_id ? `<span class="badge bg-secondary">INWise ID: ${error.inwise_id}</span>` : ''}
                    </div>
                </div>
                <p class="text-muted">${error.affected_component}</p>
                <hr>
                <h5>Error Message</h5>
                <p>${error.message}</p>
                <h5>Stack Trace</h5>
                <div class="stack-trace">${error.stack_trace || 'No stack trace available'}</div>
                <h5>Additional Information</h5>
                <ul class="list-group">
                    <li class="list-group-item"><strong>Environment:</strong> ${error.environment}</li>
                    <li class="list-group-item"><strong>Severity:</strong> ${error.severity}</li>
                    <li class="list-group-item"><strong>Impact:</strong> ${error.impact || 'Not specified'}</li>
                    <li class="list-group-item"><strong>Source:</strong> ${error.source}</li>
                    <li class="list-group-item"><strong>Timestamp:</strong> ${new Date(error.timestamp).toLocaleString()}</li>
                </ul>
                ${error.resolution ? `
                    <div class="error-resolution">
                        <h5>Resolution</h5>
                        <p>${error.resolution}</p>
                        <small>Resolved at: ${new Date(error.resolution_time).toLocaleString()}</small>
                    </div>
                ` : ''}
            </div>
        `;

        // Show/hide resolve button based on status
        document.getElementById('resolveError').style.display = 
            error.status === 'resolved' ? 'none' : 'block';

        modal.show();
    }

    function resolveError(errorId) {
        const resolution = prompt('Please enter resolution details:');
        if (resolution) {
            fetch(`/api/errors/${errorId}/resolve`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ resolution })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    modal.hide();
                    loadErrors(document.querySelector('.nav-link.active').dataset.status);
                }
            })
            .catch(error => console.error('Error resolving error:', error));
        }
    }

    function applyFilters() {
        const cards = document.querySelectorAll('.error-card');
        cards.forEach(card => {
            const error = card.querySelector('.card-title').textContent;
            const component = card.querySelector('.card-subtitle').textContent;
            const severity = card.classList.contains('error-severity-high') ? 'high' :
                           card.classList.contains('error-severity-medium') ? 'medium' : 'low';
            const source = card.querySelector('.badge.bg-info').textContent;

            const matchesSeverity = !filters.severity || filters.severity.value === 'all' || 
                                  severity === filters.severity.value;
            const matchesComponent = !filters.component || !filters.component.value || 
                                   component.toLowerCase().includes(filters.component.value.toLowerCase());
            const matchesSearch = !filters.search || !filters.search.value || 
                                error.toLowerCase().includes(filters.search.value.toLowerCase());
            const matchesSource = !filters.source || filters.source.value === 'all' || 
                                source === filters.source.value;

            card.style.display = matchesSeverity && matchesComponent && 
                               matchesSearch && matchesSource ? 'block' : 'none';
        });
    }
});

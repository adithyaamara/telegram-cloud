// Script for handling move-folder modal.
var folderToMove    // The folder that is being moved (fetch immediately on move folder button clicked.)
document.querySelectorAll('.move-btn').forEach(function(button) {
    button.addEventListener('click', function() {
        var buttonId = button.id;   // Each folder's move button will have a different ID. Based on that get which folder's button was clicked.
        folderToMove = document.getElementById(buttonId).dataset.folder;  // copy the selected button's folder path (data-folder attribute). This is necessary for making move_folder API call.
    });
});

document.getElementById('moveConfirmBtn').addEventListener('click', function() {
    var targetFolder = document.getElementById('targetFolder').value;   // Where to move the selected folder to. (fetch after move button in modal is clicked.)
    var newNameForMovedFolder = document.getElementById('newNameForMovedFolder').value;   // target folder is same as selected folder initially, must be edited before clicking move.
    var moveButton = this;
    moveButton.disabled = true;   // Disable once clicked, to avoid multiple calls from over enthusiastic user.
    var formData = new FormData();  // Send required form data.
    formData.append('folder_to_move', folderToMove);
    formData.append('target_folder', targetFolder);
    formData.append('new_name_for_moved_folder', newNameForMovedFolder);
    fetch('/move_folder/', {    // call '/move_file/' API
        method: 'POST',
        body: formData,
    })
    .then(response => {     // Redirect is not automatic since we are using Bootstrap modal. If server response is redirect, do the redirect.
        if (response.redirected) {
            window.location.href = response.url;
        } else {     // If response is JSON. Just console log it.
            moveButton.disabled = false
            return response.json()
        }
    })
    .then(data => {
        console.log(data);
        document.getElementById("modal-pro-tip").innerHTML = data.error  // In case of error, Error is displayed in pro-tip section of modal only.
    })
    .catch(error => console.error('Error:', error));
});

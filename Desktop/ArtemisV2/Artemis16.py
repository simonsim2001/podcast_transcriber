import streamlit as st
from h2ogpte import H2OGPTE as ArtemisXSL
import csv
import os
import tempfile
import json
from io import StringIO
from dotenv import load_dotenv

load_dotenv()

# Initialize the client with your API key and endpoint from environment variables
client = ArtemisXSL(
    address=os.getenv("ADRESS"),
    api_key=os.getenv("ARTEMIS_KEY_1")
)

# Initialize the client for uploading and ingestion tasks
client_2 = ArtemisXSL(
    address=os.getenv("ADRESS"),
    api_key=os.getenv("ARTEMIS_KEY_2")
)

default_collection_id = os.getenv("DEFAULT_COLLECTION_ID")


st.title("Artemis")

# Initialize session state for chat session ID and chat name
if 'chat_session_id' not in st.session_state:
    st.session_state['chat_session_id'] = None
if 'chat_name' not in st.session_state:
    st.session_state['chat_name'] = None

def start_new_chat():
    """Create a new chat session and update session state."""
    try:
        st.session_state.chat_session_id = client.create_chat_session_on_default_collection()
        st.session_state.chat_name = "New Conversation"  # Optionally, this could be more dynamic or user-defined
        st.info("Started a new chat session.")
    except Exception as e:
        st.error(f"Failed to start a new chat session: {str(e)}")

# Function to display chat history
def display_chat_history(session_id):
    """Display the chat history for a given session ID."""
    if session_id:
        try:
            messages = client.list_chat_messages_full(chat_session_id=session_id, offset=0, limit=100)
            for message in messages:
                author = "You" if message.reply_to is None else "Artemis"
                st.write(f"{author} says: {message.content}")
        except Exception as e:
            st.error(f"Failed to load chat history for session {session_id}: {str(e)}")

# Button to start a new chat session
if st.button("Start New Chat"):
    start_new_chat()

# Display chat history if a session exists
if st.session_state.chat_session_id:
    display_chat_history(st.session_state.chat_session_id)

# Function to load and display recent chats
def load_recent_chats():
    """Load and allow selection of recent chat sessions."""
    st.sidebar.header("Chat History")
    try:
        recent_chats = client.list_recent_chat_sessions(offset=0, limit=50)
        if not recent_chats:
            st.sidebar.write("No recent chats available.")
            return

        chat_descriptions = [f"{chat.collection_name} - {chat.updated_at.strftime('%Y-%m-%d %H:%M:%S')}" for chat in recent_chats]
        chat_ids = [chat.id for chat in recent_chats]

        selected_chat_index = st.sidebar.selectbox("Select a chat:", options=range(len(chat_descriptions)), format_func=lambda x: chat_descriptions[x])
        selected_chat_id = chat_ids[selected_chat_index]

        if st.session_state.chat_session_id != selected_chat_id:
            st.session_state.chat_session_id = selected_chat_id
            st.rerun()

    except Exception as e:
        st.sidebar.error(f"Failed to load recent chats: {str(e)}")

# Sidebar for recent chat loading
load_recent_chats()


def display_references(message_id, user_question):
    """Display references for a given message, match document names with IDs, and search for chunks in each document."""
    try:
        references = client.list_chat_message_references(message_id)
        collection_metadata = client.get_collection(collection_id=default_collection_id)
        documents = client.list_documents_in_collection(collection_id=default_collection_id, offset=0, limit=100)
        
        doc_name_to_id = {doc.name: doc.id for doc in documents}
        document_chunks_fetched = {}

        if references:
            st.write("\n")  # Adding a line skip
            st.markdown("### References (up to 5):", unsafe_allow_html=True)  # Making the text a bit bigger using markdown
            for ref in references[:5]:  # Process only the first 5 references for brevity
                doc_name = ref.document_name
                score = ref.score

                document_id = doc_name_to_id.get(doc_name)
                if not document_id:
                    st.write(f"Document name '{doc_name}' not found in collection.")
                    continue

                offset = document_chunks_fetched.get(document_id, 0)

                search_results = client.search_chunks(
                    collection_id=default_collection_id,
                    query=user_question,
                    topics=[document_id],
                    offset=offset,
                    limit=1  # Fetch the next relevant chunk
                )

                if search_results:
                    result = search_results[0]
                    # Find the last complete sentence within 1000 characters
                    cutoff_index = result.text[:1000].rfind('.') + 1
                    displayed_text = result.text[:cutoff_index] if cutoff_index > 0 else result.text[:1000]
                    ref_details = f"<div style='font-family:sans-serif;font-size:16px;margin-bottom:10px;'>Document: {doc_name}, Score: {score}, Text: {displayed_text}</div>"
                    st.markdown(ref_details, unsafe_allow_html=True)

                    document_chunks_fetched[document_id] = offset + 1
                else:
                    st.write(f"No additional text found for '{doc_name}' at offset {offset}.")
        else:
            st.write("No references found for this response.")
    except Exception as e:
        st.error(f"Failed to load references: {str(e)}")


# Function to submit a question and display the response
def submit_question():
    """Submit a user question to the current chat session and display the response with references."""
    with st.form(key='Question_Form'):
        user_question = st.text_input("Ask your question here:", key="question_input")
        submit_button = st.form_submit_button("Submit")
    
    if submit_button and user_question:
        if 'chat_session_id' not in st.session_state:
            start_new_chat()
        try:
            with st.spinner('Waiting for Artemis...'):
                with client.connect(st.session_state['chat_session_id']) as session:
                    response = session.query(user_question)
                    # Display response from Artemis using the content of the response
                    st.markdown(f'<div style="font-family:sans-serif;font-size:16px">{response.content}</div>', unsafe_allow_html=True)
                    # Fetch and display references for the response, if available
                    display_references(response.id, user_question)
        except Exception as e:
            st.error(f"Failed to submit question: {str(e)}")

# Main interface for submitting questions
submit_question()


def download_conversation():
    """Allow users to download their conversation as a CSV file, with an option to include references."""
    include_references = st.radio("Include references in the download?", ("Yes (only available for the initial session)", "No"))

    if st.button("Prepare Download Conversation"):
        with st.spinner('Preparing your download, please wait...'):
            if 'chat_session_id' in st.session_state:
                try:
                    messages = client.list_chat_messages_full(chat_session_id=st.session_state['chat_session_id'], offset=0, limit=100)
                    documents = client.list_documents_in_collection(collection_id=default_collection_id, offset=0, limit=100)
                    doc_name_to_id = {doc.name: doc.id for doc in documents}
                    
                    # Default filename for download
                    filename = "conversation_with_references.csv" if include_references == "Yes (only available for the initial session)" else "conversation.csv"

                    # Create CSV in memory
                    csv_file = StringIO()
                    writer = csv.writer(csv_file)
                    headers = ['Dialogue']
                    if include_references == "Yes (only available for the initial session)":
                        headers.append('References')
                    writer.writerow(headers)

                    for message in messages:
                        if message.reply_to is None:
                            author = "You: "
                        else:
                            author = "Artemis: "
                        
                        # Create the message line
                        message_line = f"{author}{message.content}"

                        # Handle references for Artemis' messages
                        references_info = ""
                        if author == "Artemis: " and include_references == "Yes (only available for the initial session)":
                            ref_data = client.list_chat_message_references(message_id=message.id)
                            for ref in ref_data[:5]:  # Process only the first 5 references for brevity
                                doc_name = ref.document_name
                                score = ref.score
                                document_id = doc_name_to_id.get(doc_name)

                                if not document_id:
                                    references_info += f"\nDocument name '{doc_name}' not found in collection.\n\n"  # Adding line skips for clarity
                                    continue

                                search_results = client.search_chunks(
                                    collection_id=default_collection_id,
                                    query=message.content,  # Using message content as query
                                    topics=[document_id],
                                    offset=0,
                                    limit=1
                                )

                                if search_results:
                                    result = search_results[0]
                                    cutoff_index = result.text[:1000].rfind('.') + 1
                                    displayed_text = result.text[:cutoff_index] if cutoff_index > 0 else result.text[:1000]
                                    references_info += f"Document: {doc_name}, Score: {score}, Text: {displayed_text.strip()}\n\n"
                                else:
                                    references_info += f"Document: {doc_name}, Score: {score}, Text: No text found.\n\n"

                        # Write the message and references (if any)
                        row = [message_line]
                        if include_references == "Yes (only available for the initial session)":
                            row.append(references_info)
                        writer.writerow(row)

                    # Reset pointer to beginning of the StringIO object before downloading
                    csv_file.seek(0)
                    csv_bytes = csv_file.getvalue().encode()
                    csv_file.close()
                    
                    st.download_button(label="Download CSV", data=csv_bytes, file_name=filename, mime='text/csv')
                except Exception as e:
                    st.error(f"Failed to download conversation: {str(e)}")
            else:
                st.warning("No active chat session available to download.")

# Call the function within your Streamlit app
download_conversation()


def upload_and_ingest_document(collection_id, uploaded_file):
    """Uploads and ingests a single document to the specified collection using a dedicated API key."""
    tmp_path = None
    try:
        # Use a temporary file to handle the uploaded file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
            tmp.write(uploaded_file.getbuffer())
            tmp_path = tmp.name

        # Upload the document file with dedicated upload client
        with open(tmp_path, "rb") as f:
            with st.spinner(f"Uploading {uploaded_file.name}..."):
                upload_id = client_2.upload(uploaded_file.name, f)
                st.success("Upload successful.")

        # Ingest the uploaded document with a spinner indicating processing
        with st.spinner("Processing document..."):
            response = client_2.ingest_uploads(
                collection_id=collection_id,
                upload_ids=[upload_id],
                gen_doc_summaries=False,
                gen_doc_questions=False
            )
            st.success("Document processed successfully.")

    except Exception as e:
        st.error(f"Error processing {uploaded_file.name}: {e}")
    finally:
        # Clean up the temporary file if it was created
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

def delete_document(document_id):
    """Delete a specific document by ID with user confirmation."""
    # Key for storing confirmation state
    confirm_key = f"confirm_delete_{document_id}"

    if st.session_state.get(confirm_key, False):
        try:
            # Assume client_2 is correctly initialized somewhere in the script
            client_2.delete_documents([document_id])  # API request to delete document
            st.sidebar.success(f"Document {document_id} deleted successfully.")
            del st.session_state[confirm_key]  # Reset the confirmation flag
            st.rerun()  # Refresh to reflect the change in UI
        except Exception as e:
            st.sidebar.error(f"Failed to delete document: {str(e)}")
            if confirm_key in st.session_state:
                del st.session_state[confirm_key]  # Reset the confirmation flag if there was an error
    else:
        if st.sidebar.button(f"Delete {document_id}", key=f"delete_{document_id}"):
            st.session_state[confirm_key] = True  # Set the flag that deletion is confirmed
            st.sidebar.warning("Click again to confirm deletion. This action cannot be reversed!")

def list_and_delete_documents(collection_id):
    """List and provide an option to delete documents from the collection."""
    try:
        documents = client_2.list_documents_in_collection(collection_id, offset=0, limit=100)
        # Calculate the percentage of documents used
        num_documents = len(documents)
        capacity_percentage = (num_documents / 100) * 100  # Assuming 100 is the max capacity
        

        # Display capacity in a box
        st.sidebar.metric(label="Artemis Capacity on Current Data", value=f"{capacity_percentage:.0f}%", delta=None)

        if documents:
            # Display documents and deletion options in the sidebar
            for doc in documents:
                st.sidebar.text(doc.name)  # Display the document name
                delete_document(doc.id)  # Handle deletion
        else:
            st.sidebar.write("No documents available to display.")
    except Exception as e:
        st.sidebar.error(f"Error retrieving documents: {str(e)}")

def main():
    st.title("Document Management System")
    collection_id = "55456956-dd08-4b4d-ade5-52a34a762233"  # collection ID

    st.sidebar.header("Document Database")
    
    list_and_delete_documents(collection_id)  # This function now also displays capacity

    uploaded_files = st.file_uploader("Choose files to upload", type=["pdf"], accept_multiple_files=True)
    if uploaded_files and st.button('Upload and Ingest Files'):
        for uploaded_file in uploaded_files:
            # Assume upload_and_ingest_document is defined correctly somewhere
            upload_and_ingest_document(collection_id, uploaded_file)

if __name__ == "__main__":
    main()
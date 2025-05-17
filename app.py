import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

# Data Ingestion and Preprocessing
def load_and_clean_data(file_path):
    try:
        # Try loading with 'latin1' encoding to handle special characters
        df = pd.read_csv(file_path, encoding='latin1')
    except UnicodeDecodeError:
        # Fallback to 'iso-8859-1' if 'latin1' fails
        df = pd.read_csv(file_path, encoding='iso-8859-1')
    except Exception as e:
        st.error(f"Error loading file: {str(e)}")
        return None
    
    # Check for columns and map to expected names
    column_map = {
        'name': ['Restaurant Name', 'restaurant_name', 'name'],
        'location': ['City', 'Locality', 'Locality Verbose', 'Address', 'location'],
        'rating': ['Aggregate rating', 'rate', 'rating', 'Rating'],
        'cost': ['Average Cost for two', 'cost_for_two', 'approx_cost', 'cost', 'average_cost'],
        'cuisines': ['Cuisines', 'cuisine', 'Cuisine'],
        'votes': ['Votes', 'votes', 'vote_count']
    }
    
    # Track missing columns
    missing_columns = []
    available_columns = df.columns.tolist()
    
    # Rename columns to standard names if they exist
    for standard_col, possible_cols in column_map.items():
        for possible_col in possible_cols:
            if possible_col in df.columns:
                df = df.rename(columns={possible_col: standard_col})
                break
        else:
            missing_columns.append(standard_col)
    
    # Warn about missing columns
    if missing_columns:
        st.warning(f"Missing columns: {missing_columns}. Using defaults where possible. Available columns: {available_columns}")
    
    # Remove duplicates (only if name and location are available)
    duplicate_cols = [col for col in ['name', 'location'] if col in df.columns]
    if duplicate_cols:
        df = df.drop_duplicates(subset=duplicate_cols)
    
    # Drop irrelevant columns
    columns_to_drop = ['Restaurant ID', 'Country Code', 'Currency', 'Has Table booking', 'Has Online delivery', 
                      'Is delivering now', 'Switch to order menu', 'Price range', 'Rating color', 'Rating text']
    df = df.drop(columns=[col for col in columns_to_drop if col in df.columns])
    
    # Handle missing values
    df = df.dropna(thresh=len(df.columns) * 0.7)  # Drop rows with >30% missing values
    
    # Handle rating
    if 'rating' in df.columns:
        df['rating'] = pd.to_numeric(df['rating'], errors='coerce').fillna(3.0)  # Default to 3.0
    else:
        df['rating'] = 3.0  # Default rating if column is missing
    
    # Handle cost
    if 'cost' in df.columns:
        # Convert to string, remove commas, then convert to numeric
        df['cost'] = df['cost'].astype(str).str.replace(',', '', regex=False)
        df['cost'] = pd.to_numeric(df['cost'], errors='coerce')
        # Fill NaN with median of numeric values
        cost_median = df['cost'].median() if not df['cost'].isna().all() else 500
        df['cost'] = df['cost'].fillna(cost_median)
    else:
        df['cost'] = 500  # Default cost if column is missing
    
    # Handle location
    if 'location' not in df.columns:
        df['location'] = 'Unknown'
    
    # Handle cuisines
    if 'cuisines' in df.columns:
        df['cuisines'] = df['cuisines'].fillna('Unknown').str.lower()
    else:
        df['cuisines'] = 'Unknown'
    
    # Handle votes
    if 'votes' not in df.columns:
        df['votes'] = 0
    
    # Feature Engineering
    def categorize_cost(cost):
        try:
            cost = float(cost)
            if cost < 300:
                return 'low'
            elif cost < 700:
                return 'medium'
            else:
                return 'high'
        except (ValueError, TypeError):
            return 'medium'  # Default to medium if cost is invalid
    
    df['cost_category'] = df['cost'].apply(categorize_cost)
    
    # Extract primary cuisine
    df['primary_cuisine'] = df['cuisines'].apply(lambda x: x.split(',')[0].strip() if isinstance(x, str) else 'unknown')
    
    # Normalize ratings to 1-5 scale
    df['normalized_rating'] = df['rating'].clip(1, 5)
    
    return df

# Recommendation Engine
def filter_and_rank_restaurants(df, cuisines, budget, location, strategy, top_n=10):
    if df is None:
        return pd.DataFrame()
    
    # Convert inputs to lowercase for case-insensitive matching
    cuisines = [c.lower() for c in cuisines]
    location = location.lower()
    
    # Filter based on available columns
    conditions = []
    if 'primary_cuisine' in df.columns:
        conditions.append(df['primary_cuisine'].str.lower().str.contains('|'.join(cuisines), na=False))
    if 'cost_category' in df.columns:
        conditions.append(df['cost_category'].str.lower() == budget.lower())
    if 'location' in df.columns:
        conditions.append(df['location'].str.lower().str.contains(location, na=False))
    
    # Apply filters if any conditions exist
    if conditions:
        filtered_df = df
        for condition in conditions:
            filtered_df = filtered_df[condition]
    else:
        filtered_df = df
    
    # Ranking based on selected strategy
    if strategy == "A: Rating-heavy":
        filtered_df['score'] = (filtered_df['normalized_rating'] * 0.8) + \
                             (filtered_df['votes'].apply(lambda x: min(x, 1000) / 1000 if pd.notnull(x) else 0) * 0.2)
    else:  # Strategy B: Votes-heavy
        filtered_df['score'] = (filtered_df['normalized_rating'] * 0.5) + \
                             (filtered_df['votes'].apply(lambda x: min(x, 1000) / 1000 if pd.notnull(x) else 0) * 0.5)
    
    # Sort and select top N
    top_restaurants = filtered_df.sort_values(by='score', ascending=False).head(top_n)
    
    # Generate explanations
    top_restaurants['explanation'] = top_restaurants.apply(
        lambda row: f"Matched on {', '.join(cuisines)} cuisine" + 
                    (f", {budget} budget" if 'cost_category' in row else "") + 
                    (f", and {row['normalized_rating']:.1f} rating from {row['votes'] if pd.notnull(row['votes']) else 0} votes" if 'rating' in row else "") +
                    f" (Strategy: {strategy})",
        axis=1
    )
    
    return top_restaurants

# Streamlit UI
def main():
    st.title("Restaurant Recommendation System")
    
    # Initialize session state to store recommendations and preferences
    if 'recommendations' not in st.session_state:
        st.session_state.recommendations = None
        st.session_state.preferences = None
        st.session_state.filtered_df = None
    
    # Create a form for user inputs
    with st.form(key='preference_form'):
        st.header("Your Preferences")
        cuisines = st.multiselect(
            "Select Cuisine(s)", 
            options=['chinese', 'indian', 'italian', 'mexican', 'thai', 'continental'],
            default=['indian']
        )
        budget = st.selectbox("Select Budget", options=['low', 'medium', 'high'], index=1)
        location = st.text_input("Enter Location", value="Bangalore")
        strategy = st.radio("Select Recommendation Strategy", ["A: Rating-heavy", "B: Votes-heavy"], index=0)
        submit_button = st.form_submit_button(label="Get Recommendations")
    
    # Load and clean data only if form is submitted
    if submit_button:
        df = load_and_clean_data('zomato.csv')
        
        if df is None:
            st.error("Failed to load data. Please check the file and try again.")
            return
        
        # Get recommendations
        if cuisines and budget and location:
            recommendations = filter_and_rank_restaurants(df, cuisines, budget, location, strategy)
            # Store recommendations and preferences in session state
            st.session_state.recommendations = recommendations
            st.session_state.preferences = {
                'cuisines': cuisines,
                'budget': budget,
                'location': location,
                'strategy': strategy
            }
            # Store filtered dataframe for re-ranking
            conditions = []
            if 'primary_cuisine' in df.columns:
                conditions.append(df['primary_cuisine'].str.lower().str.contains('|'.join([c.lower() for c in cuisines]), na=False))
            if 'cost_category' in df.columns:
                conditions.append(df['cost_category'].str.lower() == budget.lower())
            if 'location' in df.columns:
                conditions.append(df['location'].str.lower().str.contains(location.lower(), na=False))
            filtered_df = df
            for condition in conditions:
                filtered_df = filtered_df[condition]
            st.session_state.filtered_df = filtered_df
        else:
            st.warning("Please provide all preferences (cuisine, budget, location).")
            st.session_state.recommendations = None
            st.session_state.filtered_df = None
    
    # Display recommendations if they exist in session state
    if st.session_state.recommendations is not None:
        recommendations = st.session_state.recommendations
        preferences = st.session_state.preferences
        
        if not recommendations.empty:
            st.header("Top Recommendations")
            for _, row in recommendations.iterrows():
                st.subheader(row['name'] if 'name' in row else 'Unknown Restaurant')
                st.write(f"Cuisine: {row['primary_cuisine']}")
                if 'cost_category' in row:
                    st.write(f"Price Category: {row['cost_category']}")
                if 'normalized_rating' in row:
                    st.write(f"Rating: {row['normalized_rating']:.1f}")
                st.write(f"Explanation: {row['explanation']}")
                st.markdown("---")
                
                # Map view (using Latitude and Longitude)
                if 'Latitude' in row and 'Longitude' in row and pd.notnull(row['Latitude']) and pd.notnull(row['Longitude']):
                    m = folium.Map(location=[row['Latitude'], row['Longitude']], zoom_start=15)
                    folium.Marker([row['Latitude'], row['Longitude']], popup=row['name'] if 'name' in row else 'Restaurant').add_to(m)
                    st_folium(m, width=700, height=300)
        else:
            st.warning(f"No restaurants match your preferences (cuisine: {', '.join(preferences['cuisines'])}, budget: {preferences['budget']}, location: {preferences['location']}, strategy: {preferences['strategy']}). Try adjusting your filters or using a broader location (e.g., 'Bangalore').")
        
        # Re-ranking form
        if st.session_state.filtered_df is not None:
            with st.form(key='rerank_form'):
                st.header("Re-rank Recommendations")
                new_strategy = st.selectbox("Select New Strategy", ["A: Rating-heavy", "B: Votes-heavy"], index=0 if preferences['strategy'] == "A: Rating-heavy" else 1)
                rerank_button = st.form_submit_button(label="Re-rank Recommendations")
                
                if rerank_button:
                    # Re-rank using the stored filtered dataframe and new strategy
                    recommendations = filter_and_rank_restaurants(
                        st.session_state.filtered_df,
                        preferences['cuisines'],
                        preferences['budget'],
                        preferences['location'],
                        new_strategy
                    )
                    st.session_state.recommendations = recommendations
                    st.session_state.preferences['strategy'] = new_strategy
    
    # Feedback form (separate from preference and rerank forms)
    with st.form(key='feedback_form'):
        st.header("Feedback")
        satisfaction = st.slider("How satisfied are you with the recommendations? (1-5)", 1, 5, 3, key="satisfaction")
        relevance = st.radio("Are these recommendations relevant?", ["Yes", "No"], key="relevance")
        feedback_submit = st.form_submit_button(label="Submit Feedback")
        
        if feedback_submit:
            st.success(f"Thank you! Satisfaction: {satisfaction}, Relevance: {relevance}")

if __name__ == "__main__":
    main()
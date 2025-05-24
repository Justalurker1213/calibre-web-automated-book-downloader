# pwa-frontend/Dockerfile

# Stage 1: Build the React application
FROM node:20-alpine as build-stage
WORKDIR /app

# Copy package.json and package-lock.json first for efficient caching
COPY package*.json ./

# Install Node.js dependencies
RUN npm install

# Copy the rest of your application code
COPY . .

# Build the React app
RUN npm run build

# Stage 2: Serve the built application with Nginx
FROM nginx:stable-alpine as production-stage
LABEL maintainer="Your Name <your.email@example.com>"

# Remove default Nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy your custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built React app from the build-stage to Nginx's public directory
COPY --from=build-stage /app/build /usr/share/nginx/html

# Expose port 80 for Nginx
EXPOSE 80

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]

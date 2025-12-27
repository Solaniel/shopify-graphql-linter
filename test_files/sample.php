<?php

class ShopifyService
{
    public function getProducts()
    {
        $query = <<<QUERY
query GetProducts {
  products(first: 10) {
    edges {
      node {
        id
        title
        handle
        descriptionHtml
      }
    }
  }
}
QUERY;

$query = <<<QUERY
query GetProducts {
  products(first: 10) {
    edges {
      node {
        id
        title
        handle
        descriptionHtml
        feedback {
          appFeedback {
            state
         }
        }
      }
    }
  }
}
QUERY;

        return $this->client->query($query);
    }

    public function getOrders()
    {
        $orderQuery = <<<QUERY
query GetOrders {
  orders(first: 5) {
    edges {
      node {
        id
        name
        totalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
      }
    }
  }
}
QUERY;

        return $this->client->query($orderQuery);
    }
}

